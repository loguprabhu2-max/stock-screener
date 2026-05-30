"""Data management - delete and download price data by date range.

Tables this works with:
  - stock_prices
  - sector_prices
  - index_prices

Operations:
  - Count rows in a date range (preview before delete)
  - Delete rows in a date range
  - Export rows in a date range as CSV
"""
import csv
import io
from database import get_connection, query_all


# Maps friendly names to actual table info
TABLES = {
    "stock_prices":  {"label": "Stock Prices",  "name_col": "stock_symbol"},
    "sector_prices": {"label": "Sector Prices", "name_col": "sector_name"},
    "index_prices":  {"label": "Index Prices",  "name_col": "index_name"},
}


def get_data_summary():
    """Row count + date range for each price table — for the page header."""
    summary = {}
    for table, info in TABLES.items():
        rows = query_all(
            f"""SELECT COUNT(*) AS n,
                       MIN(date) AS min_d,
                       MAX(date) AS max_d
                FROM {table}"""
        )
        r = rows[0] if rows else {}
        summary[table] = {
            "label": info["label"],
            "count": r.get("n", 0) or 0,
            "min_date": r.get("min_d"),
            "max_date": r.get("max_d"),
        }
    return summary


def count_rows_in_range(table, from_date, to_date):
    """Preview how many rows fall in a date range."""
    if table == "all":
        total = 0
        per_table = {}
        for t in TABLES:
            n = count_rows_in_range(t, from_date, to_date)["count"]
            per_table[t] = n
            total += n
        return {"count": total, "per_table": per_table}

    if table not in TABLES:
        return {"count": 0, "error": "Unknown table"}

    rows = query_all(
        f"SELECT COUNT(*) AS n FROM {table} WHERE date BETWEEN %s AND %s",
        (from_date, to_date),
    )
    return {"count": rows[0]["n"] if rows else 0}


def delete_in_range(table, from_date, to_date):
    """Delete rows in a date range. Returns rows deleted."""
    if table == "all":
        total = 0
        details = []
        for t in TABLES:
            n = delete_in_range(t, from_date, to_date)["deleted"]
            total += n
            details.append(f"{TABLES[t]['label']}: {n} rows")
        return {"deleted": total, "details": details}

    if table not in TABLES:
        return {"deleted": 0, "error": "Unknown table"}

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {table} WHERE date BETWEEN %s AND %s",
                (from_date, to_date),
            )
            count = cur.rowcount
            conn.commit()
        return {"deleted": count, "details": [f"{TABLES[table]['label']}: {count} rows"]}
    except Exception as e:
        conn.rollback()
        return {"deleted": 0, "error": str(e)}
    finally:
        conn.close()


def fetch_for_export(table, from_date, to_date):
    """Return list of rows for CSV export."""
    if table not in TABLES:
        return None, None

    name_col = TABLES[table]["name_col"]
    rows = query_all(
        f"""SELECT date, {name_col}, open, high, low, close
            FROM {table}
            WHERE date BETWEEN %s AND %s
            ORDER BY date, {name_col}""",
        (from_date, to_date),
    )
    headers = ["date", name_col, "open", "high", "low", "close"]
    return headers, rows


def export_csv(table, from_date, to_date):
    """Build a CSV string for one table's data in a date range."""
    headers, rows = fetch_for_export(table, from_date, to_date)
    if headers is None:
        return None
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(headers)
    for r in rows:
        writer.writerow([
            r["date"].strftime("%Y-%m-%d"),
            r[headers[1]],
            r["open"], r["high"], r["low"], r["close"],
        ])
    return out.getvalue()


def export_all_as_zip(from_date, to_date):
    """Build a ZIP with one CSV per table for the date range."""
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for table in TABLES:
            csv_data = export_csv(table, from_date, to_date)
            if csv_data:
                zf.writestr(f"{table}_{from_date}_to_{to_date}.csv", csv_data)
    buf.seek(0)
    return buf.read()
