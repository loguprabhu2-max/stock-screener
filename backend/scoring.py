"""Stock Scoring Strategy — dual-console design.

Return Console:
    score_return = Σ (weight_i% * N_month_return_i)

Volatility Console (optional):
    score_vol = Σ (weight_j% * N_month_volatility_j)

Final Score:
    If volatility console is used:  final = score_return / score_vol
    If volatility console is empty: final = score_return

Higher final score = better rank.
"""
import math
from collections import defaultdict
from datetime import date

from database import query_all
from date_utils import format_display


# ── Metric catalogues ─────────────────────────────────────────────────
RETURN_METRICS = {
    "1m_return":  {"label": "1 Month Return",  "trading_days": 21},
    "3m_return":  {"label": "3 Month Return",  "trading_days": 63},
    "6m_return":  {"label": "6 Month Return",  "trading_days": 126},
    "9m_return":  {"label": "9 Month Return",  "trading_days": 189},
    "12m_return": {"label": "12 Month Return", "trading_days": 252},
}

VOL_METRICS = {
    "1m_volatility": {"label": "1 Month Volatility", "trading_days": 21},
    "3m_volatility": {"label": "3 Month Volatility", "trading_days": 63},
    "6m_volatility": {"label": "6 Month Volatility", "trading_days": 126},
}

# Combined for easy lookup
ALL_METRICS = {**RETURN_METRICS, **VOL_METRICS}

PRESETS = [
    {
        "name": "6M Momentum",
        "desc": "Simple 6-month return only",
        "returns": [{"metric": "6m_return", "weight": "100"}],
        "vols":    [],
    },
    {
        "name": "Weighted Momentum",
        "desc": "70% six-month + 20% three-month + 10% one-month return",
        "returns": [
            {"metric": "6m_return", "weight": "70"},
            {"metric": "3m_return", "weight": "20"},
            {"metric": "1m_return", "weight": "10"},
        ],
        "vols": [],
    },
    {
        "name": "Momentum ÷ Volatility",
        "desc": "9M return divided by 3M volatility (Sharpe-like)",
        "returns": [{"metric": "9m_return", "weight": "100"}],
        "vols":    [{"metric": "3m_volatility", "weight": "100"}],
    },
    {
        "name": "Weighted Momentum ÷ Vol",
        "desc": "Weighted return divided by blended volatility",
        "returns": [
            {"metric": "6m_return", "weight": "70"},
            {"metric": "3m_return", "weight": "30"},
        ],
        "vols": [
            {"metric": "3m_volatility", "weight": "60"},
            {"metric": "1m_volatility", "weight": "40"},
        ],
    },
]


# ── Helpers ───────────────────────────────────────────────────────────

def _std_dev(values):
    n = len(values)
    if n < 2:
        return None
    mean = sum(values) / n
    return math.sqrt(sum((x - mean) ** 2 for x in values) / n)


def _trading_day_base(trade_date, n_days):
    """Return the date that is exactly n_days trading days before trade_date.
    Uses distinct dates present in stock_prices ordered DESC — offset n_days.
    Returns None if not enough history.
    """
    rows = query_all(
        """SELECT date FROM (
               SELECT DISTINCT date FROM stock_prices
               WHERE date <= %s
               ORDER BY date DESC
               LIMIT %s
           ) sub
           ORDER BY date
           LIMIT 1""",
        (trade_date, n_days + 1),
    )
    if rows:
        return rows[0]["date"]
    return None


# ── Main screener ──────────────────────────────────────────────────────

def run_stock_scoring(index_filter, sector_filter, min_price, max_price,
                      trade_date, return_rows, vol_rows):
    """
    return_rows: list of {"metric": "6m_return",     "weight": float or None}
    vol_rows:    list of {"metric": "3m_volatility",  "weight": float or None}

    Returns (results_list, info_dict).
    """
    if not return_rows:
        return [], {"error": "Add at least one Return metric."}

    # ── Step 1: stocks matching filters ───────────────────────────────
    where_clauses, params = [], []
    if index_filter and index_filter != "All":
        where_clauses.append("(',' || REPLACE(indexes, ', ', ',') || ',') LIKE %s")
        params.append(f"%,{index_filter},%")
    if sector_filter and sector_filter != "All":
        where_clauses.append("(',' || REPLACE(sector, ', ', ',') || ',') LIKE %s")
        params.append(f"%,{sector_filter},%")

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    stocks = query_all(
        f"SELECT stock_symbol, stock_name, sector, indexes "
        f"FROM stocks_master {where_sql} ORDER BY stock_symbol",
        tuple(params) if params else None,
    )
    if not stocks:
        return [], {"total": 0, "matched": 0, "date": str(trade_date)}

    symbols = tuple(s["stock_symbol"] for s in stocks)

    # ── Step 2: latest close on or before trade_date ──────────────────
    end_rows_db = query_all(
        """SELECT DISTINCT ON (stock_symbol) stock_symbol, close, date AS price_date
           FROM stock_prices WHERE stock_symbol IN %s AND date <= %s
           ORDER BY stock_symbol, date DESC""",
        (symbols, trade_date),
    )
    end_map = {r["stock_symbol"]: r for r in end_rows_db}

    # Price range filter
    if min_price is not None or max_price is not None:
        filtered = []
        for s in stocks:
            row = end_map.get(s["stock_symbol"])
            if not row:
                continue
            price = float(row["close"])
            if min_price is not None and price < min_price:
                continue
            if max_price is not None and price > max_price:
                continue
            filtered.append(s)
        stocks = filtered
        if not stocks:
            return [], {"total": len(end_map), "matched": 0, "date": str(trade_date)}
        symbols = tuple(s["stock_symbol"] for s in stocks)

    # ── Step 3: compute return metrics (batched) ──────────────────────
    metric_values = {}  # key -> {symbol: float}

    unique_return_keys = {r["metric"] for r in return_rows}
    for key in unique_return_keys:
        n_days    = RETURN_METRICS[key]["trading_days"]
        base_date = _trading_day_base(trade_date, n_days)
        if base_date is None:
            metric_values[key] = {}
            continue
        base_rows_db = query_all(
            """SELECT DISTINCT ON (stock_symbol) stock_symbol, close
               FROM stock_prices WHERE stock_symbol IN %s AND date <= %s
               ORDER BY stock_symbol, date DESC""",
            (symbols, base_date),
        )
        base_map = {r["stock_symbol"]: float(r["close"]) for r in base_rows_db}
        vals = {}
        for sym in symbols:
            base = base_map.get(sym)
            end  = end_map.get(sym)
            if base and end and base > 0:
                vals[sym] = (float(end["close"]) - base) / base * 100.0
        metric_values[key] = vals

    # ── Step 4: compute volatility metrics (batched) ──────────────────
    unique_vol_keys = {r["metric"] for r in vol_rows}
    for key in unique_vol_keys:
        n_days    = VOL_METRICS[key]["trading_days"]
        base_date = _trading_day_base(trade_date, n_days)
        if base_date is None:
            metric_values[key] = {}
            continue
        price_rows_db = query_all(
            """SELECT stock_symbol, close
               FROM stock_prices
               WHERE stock_symbol IN %s AND date BETWEEN %s AND %s
               ORDER BY stock_symbol, date""",
            (symbols, base_date, trade_date),
        )
        sym_closes = defaultdict(list)
        for r in price_rows_db:
            sym_closes[r["stock_symbol"]].append(float(r["close"]))

        vals = {}
        for sym, closes in sym_closes.items():
            if len(closes) < 5:
                continue
            daily_rets = [(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
            sd = _std_dev(daily_rets)
            if sd is not None:
                vals[sym] = sd * math.sqrt(252) * 100  # annualised %
        metric_values[key] = vals

    # ── Step 5: determine weighting mode ─────────────────────────────
    def _weighted_sum(rows, sym):
        """Compute weighted sum for a set of rows for one symbol.
           Returns (value, all_data_found).
        """
        total_w  = sum(abs(r["weight"] or 0) for r in rows)
        use_w    = total_w > 0
        total    = 0.0
        for r in rows:
            val = metric_values.get(r["metric"], {}).get(sym)
            if val is None:
                return None, False
            if use_w:
                total += (r["weight"] or 0) / 100.0 * val
            else:
                total += val
        if not use_w and rows:
            total /= len(rows)
        return total, True

    # ── Step 6: build scored results ─────────────────────────────────
    results = []
    for s in stocks:
        sym = s["stock_symbol"]

        ret_score, ret_ok = _weighted_sum(return_rows, sym)
        if not ret_ok:
            continue

        final_score = ret_score
        vol_score   = None

        if vol_rows:
            vol_score, vol_ok = _weighted_sum(vol_rows, sym)
            if not vol_ok:
                continue
            if vol_score and vol_score != 0:
                final_score = ret_score / vol_score
            else:
                continue  # avoid divide-by-zero

        end_row = end_map.get(sym)

        # Collect metric display values
        ret_metric_vals = {r["metric"]: round(metric_values.get(r["metric"], {}).get(sym, 0), 2)
                           for r in return_rows}
        vol_metric_vals = {r["metric"]: round(metric_values.get(r["metric"], {}).get(sym, 0), 2)
                           for r in vol_rows}

        results.append({
            "stock_symbol":   sym,
            "stock_name":     s["stock_name"],
            "sector":         s["sector"],
            "indexes":        s["indexes"],
            "close":          round(float(end_row["close"]), 2) if end_row else None,
            "price_date":     format_display(end_row["price_date"]) if end_row else "",
            "score":          round(final_score, 4),
            "return_score":   round(ret_score, 4),
            "vol_score":      round(vol_score, 4) if vol_score is not None else None,
            "ret_metrics":    ret_metric_vals,
            "vol_metrics":    vol_metric_vals,
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    for i, r in enumerate(results, 1):
        r["rank"] = i

    return results, {
        "total":       len(stocks),
        "matched":     len(results),
        "excluded":    len(stocks) - len(results),
        "date":        format_display(trade_date),
        "use_vol":     bool(vol_rows),
    }
