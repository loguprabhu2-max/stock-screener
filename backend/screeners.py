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


def _latest_close(table, name_col, name_val):
    """Get most recent (date, close) for an item from its price table."""
    rows = query_all(
        f"""SELECT date, close FROM {table}
            WHERE {name_col} = %s
            ORDER BY date DESC LIMIT 1""",
        (name_val,),
    )
    if not rows:
        return None, None
    return rows[0]["date"], float(rows[0]["close"])


# ============================================================
# Stock Screener
# ============================================================

def run_stock_screener(index_filter, sector_filter, from_date, to_date, threshold_pct):
    """
    Filter stocks by index AND/OR sector, then by % return between dates.

    index_filter:  "All" or a specific index name
    sector_filter: "All" or a specific sector name
    from_date, to_date: date objects
    threshold_pct: float (only stocks with return >= this are returned)

    Returns: (results_list, info_dict)
      results_list: list of dicts with stock data and % return
      info_dict: counts of stocks considered/excluded (for transparency)
    """
    # Step 1: Pick stocks matching index + sector filter
    where_clauses = []
    params = []
    if index_filter and index_filter != "All":
        # indexes column is comma-separated; match exact name
        where_clauses.append(
            "(',' || REPLACE(indexes, ', ', ',') || ',') LIKE %s"
        )
        params.append(f"%,{index_filter},%")
    if sector_filter and sector_filter != "All":
        where_clauses.append("sector = %s")
        params.append(sector_filter)

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

    # Step 2: For each stock, find base_close (strictly before from_date)
    # and end_close (on or before to_date) and compute return.
    results = []
    excluded = 0
    for s in stocks:
        symbol = s["stock_symbol"]

        base_row = query_all(
            """SELECT date, close FROM stock_prices
               WHERE stock_symbol = %s AND date < %s
               ORDER BY date DESC LIMIT 1""",
            (symbol, from_date),
        )
        end_row = query_all(
            """SELECT date, close FROM stock_prices
               WHERE stock_symbol = %s AND date <= %s
               ORDER BY date DESC LIMIT 1""",
            (symbol, to_date),
        )

        if not base_row or not end_row:
            excluded += 1
            continue

        base_close = float(base_row[0]["close"])
        end_close = float(end_row[0]["close"])
        if base_close == 0:
            excluded += 1
            continue

        ret_pct = (end_close - base_close) / base_close * 100.0
        if ret_pct >= threshold_pct:
            latest_date, latest_close = _latest_close("stock_prices", "stock_symbol", symbol)
            results.append({
                "stock_symbol": symbol,
                "stock_name": s["stock_name"],
                "sector": s["sector"],
                "indexes": s["indexes"],
                "base_date": format_display(base_row[0]["date"]),
                "base_close": round(base_close, 2),
                "end_date": format_display(end_row[0]["date"]),
                "end_close": round(end_close, 2),
                "latest_date": format_display(latest_date) if latest_date else "",
                "latest_price": round(latest_close, 2) if latest_close is not None else None,
                "return_pct": round(ret_pct, 2),
            })

    # Sort by return_pct descending
    results.sort(key=lambda r: r["return_pct"], reverse=True)

    return results, {
        "total": len(stocks),
        "matched": len(results),
        "excluded_no_data": excluded,
    }


# ============================================================
# Sector Screener
# ============================================================

def run_sector_screener(from_date, to_date, threshold_pct):
    """All sectors, ranked by close-to-close % return."""
    sectors = query_all(
        "SELECT sector_name FROM sectors_master ORDER BY sector_name"
    )
    if not sectors:
        return [], {"total": 0, "matched": 0, "excluded_no_data": 0}

    results = []
    excluded = 0
    for s in sectors:
        name = s["sector_name"]

        base_row = query_all(
            """SELECT date, close FROM sector_prices
               WHERE sector_name = %s AND date < %s
               ORDER BY date DESC LIMIT 1""",
            (name, from_date),
        )
        end_row = query_all(
            """SELECT date, close FROM sector_prices
               WHERE sector_name = %s AND date <= %s
               ORDER BY date DESC LIMIT 1""",
            (name, to_date),
        )

        if not base_row or not end_row:
            excluded += 1
            continue

        base_close = float(base_row[0]["close"])
        end_close = float(end_row[0]["close"])
        if base_close == 0:
            excluded += 1
            continue

        ret_pct = (end_close - base_close) / base_close * 100.0
        if ret_pct >= threshold_pct:
            latest_date, latest_close = _latest_close("sector_prices", "sector_name", name)
            results.append({
                "sector_name": name,
                "base_date": format_display(base_row[0]["date"]),
                "base_close": round(base_close, 2),
                "end_date": format_display(end_row[0]["date"]),
                "end_close": round(end_close, 2),
                "latest_date": format_display(latest_date) if latest_date else "",
                "latest_price": round(latest_close, 2) if latest_close is not None else None,
                "return_pct": round(ret_pct, 2),
            })

    results.sort(key=lambda r: r["return_pct"], reverse=True)

    return results, {
        "total": len(sectors),
        "matched": len(results),
        "excluded_no_data": excluded,
    }


# ============================================================
# Index Screener
# ============================================================

def run_index_screener(from_date, to_date, threshold_pct):
    """All indexes, ranked by close-to-close % return."""
    indexes = query_all(
        "SELECT index_name FROM indexes_master ORDER BY index_name"
    )
    if not indexes:
        return [], {"total": 0, "matched": 0, "excluded_no_data": 0}

    results = []
    excluded = 0
    for ix in indexes:
        name = ix["index_name"]

        base_row = query_all(
            """SELECT date, close FROM index_prices
               WHERE index_name = %s AND date < %s
               ORDER BY date DESC LIMIT 1""",
            (name, from_date),
        )
        end_row = query_all(
            """SELECT date, close FROM index_prices
               WHERE index_name = %s AND date <= %s
               ORDER BY date DESC LIMIT 1""",
            (name, to_date),
        )

        if not base_row or not end_row:
            excluded += 1
            continue

        base_close = float(base_row[0]["close"])
        end_close = float(end_row[0]["close"])
        if base_close == 0:
            excluded += 1
            continue

        ret_pct = (end_close - base_close) / base_close * 100.0
        if ret_pct >= threshold_pct:
            latest_date, latest_close = _latest_close("index_prices", "index_name", name)
            results.append({
                "index_name": name,
                "base_date": format_display(base_row[0]["date"]),
                "base_close": round(base_close, 2),
                "end_date": format_display(end_row[0]["date"]),
                "end_close": round(end_close, 2),
                "latest_date": format_display(latest_date) if latest_date else "",
                "latest_price": round(latest_close, 2) if latest_close is not None else None,
                "return_pct": round(ret_pct, 2),
            })

    results.sort(key=lambda r: r["return_pct"], reverse=True)

    return results, {
        "total": len(indexes),
        "matched": len(results),
        "excluded_no_data": excluded,
    }
