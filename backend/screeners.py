"""Screener logic.

All three screeners (stock, sector, index) compute close-to-close % return
between a From Date and a To Date.

Date rule (per user spec):
  - Use the most recent trading day's Close STRICTLY BEFORE From Date as the base.
  - Use the most recent trading day's Close ON OR BEFORE To Date as the end.
  - This handles weekends/holidays uniformly.

Return formula:
  return_pct = (end_close - base_close) / base_close * 100

A row is included when return_pct >= threshold (user-supplied %).

PERFORMANCE: All three screeners use single batched queries (DISTINCT ON)
instead of per-item loops. This keeps the page fast even with years of data.
"""
from datetime import date, datetime
from database import query_all
from date_utils import format_display


# ============================================================
# Helpers
# ============================================================

def parse_iso_date(s):
    """Parse YYYY-MM-DD; return None if invalid."""
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def fetch_filter_options():
    """Return dropdown options for screener forms."""
    indexes = [r["index_name"] for r in query_all(
        "SELECT index_name FROM indexes_master ORDER BY index_name"
    )]
    sectors = [r["sector_name"] for r in query_all(
        "SELECT sector_name FROM sectors_master ORDER BY sector_name"
    )]
    return {"indexes": indexes, "sectors": sectors}


def get_available_dates(table):
    """Return sorted list of unique dates (YYYY-MM-DD) present in a price table."""
    rows = query_all(f"SELECT DISTINCT date FROM {table} ORDER BY date")
    return [r["date"].strftime("%Y-%m-%d") for r in rows]


def get_date_range(table):
    """Return min and max available date as ISO strings, plus count."""
    row = query_all(
        f"SELECT MIN(date) AS min_d, MAX(date) AS max_d, COUNT(DISTINCT date) AS days FROM {table}"
    )
    if not row or not row[0]["min_d"]:
        return {"min": None, "max": None, "days": 0,
                "min_display": "", "max_display": ""}
    r = row[0]
    return {
        "min": r["min_d"].strftime("%Y-%m-%d"),
        "max": r["max_d"].strftime("%Y-%m-%d"),
        "days": r["days"],
        "min_display": format_display(r["min_d"]),
        "max_display": format_display(r["max_d"]),
    }


# ============================================================
# Stock Screener (optimized: single batched queries)
# ============================================================

def run_stock_screener(index_filter, sector_filter, from_date, to_date, threshold_pct):
    """
    Filter stocks by index AND/OR sector, then by % return between dates.

    Uses 4 total queries regardless of stock count:
      1. List of matching stocks
      2. Base close for all stocks (strictly before from_date)
      3. End close + latest close for all stocks (<= to_date)
      4. Avg delivery % for all stocks in [from_date, to_date]
    """
    # Step 1: Pick stocks matching index + sector filter
    where_clauses = []
    params = []
    if index_filter and index_filter != "All":
        where_clauses.append(
            "(',' || REPLACE(indexes, ', ', ',') || ',') LIKE %s"
        )
        params.append(f"%,{index_filter},%")
    if sector_filter and sector_filter != "All":
        where_clauses.append(
            "(',' || REPLACE(sector, ', ', ',') || ',') LIKE %s"
        )
        params.append(f"%,{sector_filter},%")

    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)

    stocks = query_all(
        f"""SELECT stock_symbol, stock_name, sector, indexes
            FROM stocks_master {where_sql}
            ORDER BY stock_symbol""",
        tuple(params) if params else None,
    )

    if not stocks:
        return [], {"total": 0, "matched": 0, "excluded_no_data": 0}

    symbols = tuple(s["stock_symbol"] for s in stocks)

    # Step 2: Base close (most recent close strictly BEFORE from_date) for ALL stocks
    base_rows = query_all(
        """SELECT DISTINCT ON (stock_symbol)
                  stock_symbol, date, close
           FROM stock_prices
           WHERE stock_symbol IN %s AND date < %s
           ORDER BY stock_symbol, date DESC""",
        (symbols, from_date),
    )
    base_map = {r["stock_symbol"]: r for r in base_rows}

    # Step 3: End close (most recent close ON OR BEFORE to_date) for ALL stocks
    end_rows = query_all(
        """SELECT DISTINCT ON (stock_symbol)
                  stock_symbol, date, close
           FROM stock_prices
           WHERE stock_symbol IN %s AND date <= %s
           ORDER BY stock_symbol, date DESC""",
        (symbols, to_date),
    )
    end_map = {r["stock_symbol"]: r for r in end_rows}

    # Step 3b: Latest close overall (for the "Latest Price" column) for ALL stocks
    latest_rows = query_all(
        """SELECT DISTINCT ON (stock_symbol)
                  stock_symbol, date, close
           FROM stock_prices
           WHERE stock_symbol IN %s
           ORDER BY stock_symbol, date DESC""",
        (symbols,),
    )
    latest_map = {r["stock_symbol"]: r for r in latest_rows}

    # Step 4: Avg delivery % across screening window for ALL stocks
    delivery_rows = query_all(
        """SELECT stock_symbol, AVG(delivery_pct) AS avg_dp
           FROM stock_prices
           WHERE stock_symbol IN %s
             AND date BETWEEN %s AND %s
             AND delivery_pct IS NOT NULL
           GROUP BY stock_symbol""",
        (symbols, from_date, to_date),
    )
    delivery_map = {r["stock_symbol"]: r["avg_dp"] for r in delivery_rows}

    # Step 5: Compute returns in Python (cheap now — no DB calls)
    results = []
    excluded = 0
    for s in stocks:
        symbol = s["stock_symbol"]
        base_row = base_map.get(symbol)
        end_row = end_map.get(symbol)

        if not base_row or not end_row:
            excluded += 1
            continue

        base_close = float(base_row["close"])
        end_close = float(end_row["close"])
        if base_close == 0:
            excluded += 1
            continue

        ret_pct = (end_close - base_close) / base_close * 100.0
        if ret_pct >= threshold_pct:
            latest_row = latest_map.get(symbol)
            avg_dp = delivery_map.get(symbol)
            avg_dp_val = round(float(avg_dp), 2) if avg_dp is not None else None

            results.append({
                "stock_symbol": symbol,
                "stock_name": s["stock_name"],
                "sector": s["sector"],
                "indexes": s["indexes"],
                "base_date": format_display(base_row["date"]),
                "base_close": round(base_close, 2),
                "end_date": format_display(end_row["date"]),
                "end_close": round(end_close, 2),
                "latest_date": format_display(latest_row["date"]) if latest_row else "",
                "latest_price": round(float(latest_row["close"]), 2) if latest_row else None,
                "return_pct": round(ret_pct, 2),
                "avg_delivery_pct": avg_dp_val,
            })

    results.sort(key=lambda r: r["return_pct"], reverse=True)

    return results, {
        "total": len(stocks),
        "matched": len(results),
        "excluded_no_data": excluded,
    }


# ============================================================
# Sector Screener (optimized)
# ============================================================

def run_sector_screener(from_date, to_date, threshold_pct):
    """All sectors, ranked by close-to-close % return."""
    sectors = query_all(
        "SELECT sector_name FROM sectors_master ORDER BY sector_name"
    )
    if not sectors:
        return [], {"total": 0, "matched": 0, "excluded_no_data": 0}

    names = tuple(s["sector_name"] for s in sectors)

    base_rows = query_all(
        """SELECT DISTINCT ON (sector_name)
                  sector_name, date, close
           FROM sector_prices
           WHERE sector_name IN %s AND date < %s
           ORDER BY sector_name, date DESC""",
        (names, from_date),
    )
    base_map = {r["sector_name"]: r for r in base_rows}

    end_rows = query_all(
        """SELECT DISTINCT ON (sector_name)
                  sector_name, date, close
           FROM sector_prices
           WHERE sector_name IN %s AND date <= %s
           ORDER BY sector_name, date DESC""",
        (names, to_date),
    )
    end_map = {r["sector_name"]: r for r in end_rows}

    latest_rows = query_all(
        """SELECT DISTINCT ON (sector_name)
                  sector_name, date, close
           FROM sector_prices
           WHERE sector_name IN %s
           ORDER BY sector_name, date DESC""",
        (names,),
    )
    latest_map = {r["sector_name"]: r for r in latest_rows}

    results = []
    excluded = 0
    for s in sectors:
        name = s["sector_name"]
        base_row = base_map.get(name)
        end_row = end_map.get(name)

        if not base_row or not end_row:
            excluded += 1
            continue

        base_close = float(base_row["close"])
        end_close = float(end_row["close"])
        if base_close == 0:
            excluded += 1
            continue

        ret_pct = (end_close - base_close) / base_close * 100.0
        if ret_pct >= threshold_pct:
            latest_row = latest_map.get(name)
            results.append({
                "sector_name": name,
                "base_date": format_display(base_row["date"]),
                "base_close": round(base_close, 2),
                "end_date": format_display(end_row["date"]),
                "end_close": round(end_close, 2),
                "latest_date": format_display(latest_row["date"]) if latest_row else "",
                "latest_price": round(float(latest_row["close"]), 2) if latest_row else None,
                "return_pct": round(ret_pct, 2),
            })

    results.sort(key=lambda r: r["return_pct"], reverse=True)

    return results, {
        "total": len(sectors),
        "matched": len(results),
        "excluded_no_data": excluded,
    }


# ============================================================
# Index Screener (optimized)
# ============================================================

def run_index_screener(from_date, to_date, threshold_pct):
    """All indexes, ranked by close-to-close % return."""
    indexes = query_all(
        "SELECT index_name FROM indexes_master ORDER BY index_name"
    )
    if not indexes:
        return [], {"total": 0, "matched": 0, "excluded_no_data": 0}

    names = tuple(ix["index_name"] for ix in indexes)

    base_rows = query_all(
        """SELECT DISTINCT ON (index_name)
                  index_name, date, close
           FROM index_prices
           WHERE index_name IN %s AND date < %s
           ORDER BY index_name, date DESC""",
        (names, from_date),
    )
    base_map = {r["index_name"]: r for r in base_rows}

    end_rows = query_all(
        """SELECT DISTINCT ON (index_name)
                  index_name, date, close
           FROM index_prices
           WHERE index_name IN %s AND date <= %s
           ORDER BY index_name, date DESC""",
        (names, to_date),
    )
    end_map = {r["index_name"]: r for r in end_rows}

    latest_rows = query_all(
        """SELECT DISTINCT ON (index_name)
                  index_name, date, close
           FROM index_prices
           WHERE index_name IN %s
           ORDER BY index_name, date DESC""",
        (names,),
    )
    latest_map = {r["index_name"]: r for r in latest_rows}

    results = []
    excluded = 0
    for ix in indexes:
        name = ix["index_name"]
        base_row = base_map.get(name)
        end_row = end_map.get(name)

        if not base_row or not end_row:
            excluded += 1
            continue

        base_close = float(base_row["close"])
        end_close = float(end_row["close"])
        if base_close == 0:
            excluded += 1
            continue

        ret_pct = (end_close - base_close) / base_close * 100.0
        if ret_pct >= threshold_pct:
            latest_row = latest_map.get(name)
            results.append({
                "index_name": name,
                "base_date": format_display(base_row["date"]),
                "base_close": round(base_close, 2),
                "end_date": format_display(end_row["date"]),
                "end_close": round(end_close, 2),
                "latest_date": format_display(latest_row["date"]) if latest_row else "",
                "latest_price": round(float(latest_row["close"]), 2) if latest_row else None,
                "return_pct": round(ret_pct, 2),
            })

    results.sort(key=lambda r: r["return_pct"], reverse=True)

    return results, {
        "total": len(indexes),
        "matched": len(results),
        "excluded_no_data": excluded,
    }


# ============================================================
# Arbitrage Trade Screener (optimized: single JOIN query)
# ============================================================

def run_arbitrage_screener(trade_date, threshold_pct):
    """
    For a given date, join future_daily with stock_prices on stock_symbol.
    Uses the most recent stock_prices close ON OR BEFORE trade_date.
    Returns rows where:
        diff_pct = (future_close - spot_close) / spot_close * 100 >= threshold_pct

    Single CTE query — no Python loops over DB calls.
    """
    # Fetch futures for the given date
    future_rows = query_all(
        "SELECT stock_symbol, future_index, close AS fut_close, date AS fut_date "
        "FROM future_daily WHERE date = %s",
        (trade_date,),
    )

    if not future_rows:
        return [], {
            "total_futures": 0, "matched": 0, "no_spot": 0,
            "date": trade_date.strftime("%Y-%m-%d"),
            "error": f"No futures data found for {format_display(trade_date)}.",
        }

    # Fetch spot prices for the exact same date
    symbols = tuple(r["stock_symbol"] for r in future_rows)
    spot_rows = query_all(
        "SELECT stock_symbol, close AS spot_close, date AS spot_date "
        "FROM stock_prices WHERE date = %s AND stock_symbol IN %s",
        (trade_date, symbols),
    )
    spot_map = {r["stock_symbol"]: r for r in spot_rows}

    results = []
    no_spot = []
    for r in future_rows:
        sym = r["stock_symbol"]
        spot = spot_map.get(sym)
        if not spot:
            no_spot.append(sym)
            continue
        spot_close = float(spot["spot_close"])
        if spot_close == 0:
            continue
        fut_close = float(r["fut_close"])
        difference = fut_close - spot_close
        diff_pct = difference / spot_close * 100.0
        if diff_pct >= threshold_pct:
            results.append({
                "stock_symbol": sym,
                "future_index": r["future_index"],
                "fut_close":    round(fut_close, 2),
                "spot_close":   round(spot_close, 2),
                "fut_date":     format_display(r["fut_date"]),
                "spot_date":    format_display(spot["spot_date"]),
                "difference":   round(difference, 2),
                "diff_pct":     round(diff_pct, 2),
            })

    results.sort(key=lambda x: x["diff_pct"], reverse=True)

    return results, {
        "total_futures": len(future_rows),
        "matched": len(results),
        "no_spot": no_spot,
        "date": trade_date.strftime("%Y-%m-%d"),
    }


def get_available_dates_future():
    """Return sorted list of unique dates in future_daily."""
    rows = query_all("SELECT DISTINCT date FROM future_daily ORDER BY date")
    return [r["date"].strftime("%Y-%m-%d") for r in rows]


def get_date_range_future():
    """Return min/max date range for future_daily."""
    row = query_all(
        "SELECT MIN(date) AS min_d, MAX(date) AS max_d, COUNT(DISTINCT date) AS days FROM future_daily"
    )
    if not row or not row[0]["min_d"]:
        return {"min": None, "max": None, "days": 0, "min_display": "", "max_display": ""}
    r = row[0]
    return {
        "min": r["min_d"].strftime("%Y-%m-%d"),
        "max": r["max_d"].strftime("%Y-%m-%d"),
        "days": r["days"],
        "min_display": format_display(r["min_d"]),
        "max_display": format_display(r["max_d"]),
    }
