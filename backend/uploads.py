"""Upload validators and DB writers for all 6 data files.

Each upload type:
  1. Parses CSV or XLSX into a pandas DataFrame.
  2. Runs strict validation (collects ALL errors, returns them).
  3. If errors -> reject; otherwise inserts to DB.

Validation returns: (is_valid, errors_list, dataframe_or_none)
Insert returns:     (success_bool, message, rows_affected)
"""
import io
from datetime import datetime
import pandas as pd

from database import get_connection, query_all
from date_utils import parse_flexible_date


# ---------- Helpers ----------

def parse_file(file_storage):
    """Read uploaded file into DataFrame. Returns (df, error_message_or_None)."""
    filename = (file_storage.filename or "").lower()
    try:
        raw = file_storage.read()
        if filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False)
        elif filename.endswith(".xlsx") or filename.endswith(".xls"):
            df = pd.read_excel(io.BytesIO(raw), dtype=str, keep_default_na=False)
        else:
            return None, "File must be .csv or .xlsx"
        df.columns = [str(c).strip() for c in df.columns]
        for col in df.columns:
            df[col] = df[col].astype(str).str.strip()
        return df, None
    except Exception as e:
        return None, f"Could not read file: {e}"


def check_required_columns(df, required):
    missing = [c for c in required if c not in df.columns]
    if missing:
        return [f"Missing required column(s): {', '.join(missing)}"]
    return []


def is_valid_date(s):
    """Accept multiple formats; see date_utils.parse_flexible_date."""
    return parse_flexible_date(s) is not None


def to_iso_date(s):
    """Convert any accepted format to YYYY-MM-DD string (for DB)."""
    d = parse_flexible_date(s)
    return d.strftime("%Y-%m-%d") if d else None


def is_valid_number(s):
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


def excel_row_number(idx):
    return idx + 2


# ============================================================
# MASTER FILE VALIDATORS + INSERTERS
# ============================================================

def validate_indexes_master(df):
    errors = []
    errors += check_required_columns(df, ["index_name"])
    if errors:
        return False, errors, None

    seen = set()
    for idx, row in df.iterrows():
        rn = excel_row_number(idx)
        name = row["index_name"]
        if not name:
            errors.append(f"Row {rn} | index_name | empty value")
        elif name in seen:
            errors.append(f"Row {rn} | index_name | duplicate '{name}'")
        else:
            seen.add(name)

    return (len(errors) == 0), errors, df


def insert_indexes_master(df):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM indexes_master")
            for _, row in df.iterrows():
                cur.execute(
                    "INSERT INTO indexes_master (index_name) VALUES (%s)",
                    (row["index_name"],),
                )
            conn.commit()
        return True, f"Replaced indexes_master with {len(df)} rows.", len(df)
    except Exception as e:
        conn.rollback()
        return False, f"Database error: {e}", 0
    finally:
        conn.close()


def validate_sectors_master(df):
    """Simplified: just sector_name column."""
    errors = []
    errors += check_required_columns(df, ["sector_name"])
    if errors:
        return False, errors, None

    seen = set()
    for idx, row in df.iterrows():
        rn = excel_row_number(idx)
        name = row["sector_name"]
        if not name:
            errors.append(f"Row {rn} | sector_name | empty value")
        elif name in seen:
            errors.append(f"Row {rn} | sector_name | duplicate '{name}'")
        else:
            seen.add(name)

    return (len(errors) == 0), errors, df


def insert_sectors_master(df):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sectors_master")
            for _, row in df.iterrows():
                cur.execute(
                    "INSERT INTO sectors_master (sector_name) VALUES (%s)",
                    (row["sector_name"],),
                )
            conn.commit()
        return True, f"Replaced sectors_master with {len(df)} rows.", len(df)
    except Exception as e:
        conn.rollback()
        return False, f"Database error: {e}", 0
    finally:
        conn.close()


def validate_stocks_master(df):
    errors = []
    errors += check_required_columns(df, ["stock_symbol", "stock_name", "sector", "indexes"])
    if errors:
        return False, errors, None

    existing_indexes = {r["index_name"] for r in query_all("SELECT index_name FROM indexes_master")}
    existing_sectors = {r["sector_name"] for r in query_all("SELECT sector_name FROM sectors_master")}

    if not existing_indexes:
        errors.append("indexes_master is empty. Upload indexes_master first.")
    if not existing_sectors:
        errors.append("sectors_master is empty. Upload sectors_master first.")
    if errors:
        return False, errors, None

    seen = set()
    for idx, row in df.iterrows():
        rn = excel_row_number(idx)
        symbol = row["stock_symbol"]
        name = row["stock_name"]
        sector = row["sector"]
        idx_str = row["indexes"]

        if not symbol:
            errors.append(f"Row {rn} | stock_symbol | empty value")
        elif symbol in seen:
            errors.append(f"Row {rn} | stock_symbol | duplicate '{symbol}'")
        else:
            seen.add(symbol)

        if not name:
            errors.append(f"Row {rn} | stock_name | empty value")

        if not sector:
            errors.append(f"Row {rn} | sector | empty value")
        else:
            for sec in [x.strip() for x in sector.split(",") if x.strip()]:
                if sec not in existing_sectors:
                    errors.append(f"Row {rn} | sector | '{sec}' not found in sectors_master")

        if not idx_str:
            errors.append(f"Row {rn} | indexes | empty value")
        else:
            for ix in [x.strip() for x in idx_str.split(",") if x.strip()]:
                if ix not in existing_indexes:
                    errors.append(f"Row {rn} | indexes | '{ix}' not found in indexes_master")

    return (len(errors) == 0), errors, df


def insert_stocks_master(df):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM stocks_master")
            for _, row in df.iterrows():
                cur.execute(
                    """INSERT INTO stocks_master (stock_symbol, stock_name, sector, indexes)
                       VALUES (%s, %s, %s, %s)""",
                    (row["stock_symbol"], row["stock_name"], row["sector"], row["indexes"]),
                )
            conn.commit()
        return True, f"Replaced stocks_master with {len(df)} rows.", len(df)
    except Exception as e:
        conn.rollback()
        return False, f"Database error: {e}", 0
    finally:
        conn.close()


# ============================================================
# DAILY PRICE VALIDATORS + INSERTERS  (UPSERT on duplicate)
# ============================================================

# Numeric columns required in stock_prices uploads (extended)
STOCK_NUMERIC_COLS = [
    "open", "high", "low", "close",
    "total_trade_qty", "turnover_lakhs", "no_of_trades",
    "delivery_qty", "delivery_pct",
]
# Generic OHLC for sector/index (unchanged)
OHLC_COLS = ["open", "high", "low", "close"]


def _validate_numeric_row(rn, row, cols, errors):
    """Each named column must have a parseable number. Returns True if no errors."""
    ok = True
    for c in cols:
        v = row.get(c, "")
        if not v:
            errors.append(f"Row {rn} | {c} | empty value")
            ok = False
        elif not is_valid_number(v):
            errors.append(f"Row {rn} | {c} | '{v}' is not a number")
            ok = False
    return ok


def _validate_ohlc_row(rn, row, errors):
    """Legacy helper for sector/index uploads. Validates open/high/low/close only."""
    return _validate_numeric_row(rn, row, OHLC_COLS, errors)


def validate_stock_prices(df):
    errors = []
    errors += check_required_columns(df, [
        "date", "stock_symbol", "open", "high", "low", "close",
        "total_trade_qty", "turnover_lakhs", "no_of_trades",
        "delivery_qty", "delivery_pct",
    ])
    if errors:
        return False, errors, None

    valid_symbols = {r["stock_symbol"] for r in query_all("SELECT stock_symbol FROM stocks_master")}
    if not valid_symbols:
        errors.append("stocks_master is empty. Upload stocks_master first.")
        return False, errors, None

    seen = set()
    for idx, row in df.iterrows():
        rn = excel_row_number(idx)
        date_s = row["date"]
        symbol = row["stock_symbol"]

        if not date_s:
            errors.append(f"Row {rn} | date | empty value")
        elif not is_valid_date(date_s):
            errors.append(f"Row {rn} | date | '{date_s}' is not a recognized date (try DD-MM-YYYY, DD/MM/YYYY, or YYYY-MM-DD)")

        if not symbol:
            errors.append(f"Row {rn} | stock_symbol | empty value")
        elif symbol not in valid_symbols:
            errors.append(f"Row {rn} | stock_symbol | '{symbol}' not found in stocks_master")

        key = (date_s, symbol)
        if key in seen:
            errors.append(f"Row {rn} | (date, stock_symbol) | duplicate within file: {date_s}, {symbol}")
        else:
            seen.add(key)

        _validate_numeric_row(rn, row, STOCK_NUMERIC_COLS, errors)

    return (len(errors) == 0), errors, df


def insert_stock_prices(df):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for _, row in df.iterrows():
                iso_date = to_iso_date(row["date"])
                cur.execute(
                    """INSERT INTO stock_prices (
                           date, stock_symbol,
                           open, high, low, close,
                           total_trade_qty, turnover_lakhs, no_of_trades,
                           delivery_qty, delivery_pct
                       )
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (date, stock_symbol) DO UPDATE SET
                         open = EXCLUDED.open, high = EXCLUDED.high,
                         low = EXCLUDED.low, close = EXCLUDED.close,
                         total_trade_qty = EXCLUDED.total_trade_qty,
                         turnover_lakhs = EXCLUDED.turnover_lakhs,
                         no_of_trades = EXCLUDED.no_of_trades,
                         delivery_qty = EXCLUDED.delivery_qty,
                         delivery_pct = EXCLUDED.delivery_pct""",
                    (iso_date, row["stock_symbol"],
                     row["open"], row["high"], row["low"], row["close"],
                     row["total_trade_qty"], row["turnover_lakhs"], row["no_of_trades"],
                     row["delivery_qty"], row["delivery_pct"]),
                )
            conn.commit()
        return True, f"Inserted/updated {len(df)} rows in stock_prices.", len(df)
    except Exception as e:
        conn.rollback()
        return False, f"Database error: {e}", 0
    finally:
        conn.close()


def validate_sector_prices(df):
    errors = []
    errors += check_required_columns(df, ["date", "sector_name", "open", "high", "low", "close"])
    if errors:
        return False, errors, None

    valid_sectors = {r["sector_name"] for r in query_all("SELECT sector_name FROM sectors_master")}
    if not valid_sectors:
        errors.append("sectors_master is empty. Upload sectors_master first.")
        return False, errors, None

    seen = set()
    for idx, row in df.iterrows():
        rn = excel_row_number(idx)
        date_s = row["date"]
        sector = row["sector_name"]

        if not date_s:
            errors.append(f"Row {rn} | date | empty value")
        elif not is_valid_date(date_s):
            errors.append(f"Row {rn} | date | '{date_s}' is not a recognized date (try DD-MM-YYYY, DD/MM/YYYY, or YYYY-MM-DD)")

        if not sector:
            errors.append(f"Row {rn} | sector_name | empty value")
        elif sector not in valid_sectors:
            errors.append(f"Row {rn} | sector_name | '{sector}' not found in sectors_master")

        key = (date_s, sector)
        if key in seen:
            errors.append(f"Row {rn} | (date, sector_name) | duplicate within file")
        else:
            seen.add(key)

        _validate_ohlc_row(rn, row, errors)

    return (len(errors) == 0), errors, df


def insert_sector_prices(df):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for _, row in df.iterrows():
                iso_date = to_iso_date(row["date"])
                cur.execute(
                    """INSERT INTO sector_prices (date, sector_name, open, high, low, close)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON CONFLICT (date, sector_name) DO UPDATE SET
                         open = EXCLUDED.open, high = EXCLUDED.high,
                         low = EXCLUDED.low, close = EXCLUDED.close""",
                    (iso_date, row["sector_name"],
                     row["open"], row["high"], row["low"], row["close"]),
                )
            conn.commit()
        return True, f"Inserted/updated {len(df)} rows in sector_prices.", len(df)
    except Exception as e:
        conn.rollback()
        return False, f"Database error: {e}", 0
    finally:
        conn.close()


def validate_index_prices(df):
    errors = []
    errors += check_required_columns(df, ["date", "index_name", "open", "high", "low", "close"])
    if errors:
        return False, errors, None

    valid_indexes = {r["index_name"] for r in query_all("SELECT index_name FROM indexes_master")}
    if not valid_indexes:
        errors.append("indexes_master is empty. Upload indexes_master first.")
        return False, errors, None

    seen = set()
    for idx, row in df.iterrows():
        rn = excel_row_number(idx)
        date_s = row["date"]
        index_name = row["index_name"]

        if not date_s:
            errors.append(f"Row {rn} | date | empty value")
        elif not is_valid_date(date_s):
            errors.append(f"Row {rn} | date | '{date_s}' is not a recognized date (try DD-MM-YYYY, DD/MM/YYYY, or YYYY-MM-DD)")

        if not index_name:
            errors.append(f"Row {rn} | index_name | empty value")
        elif index_name not in valid_indexes:
            errors.append(f"Row {rn} | index_name | '{index_name}' not found in indexes_master")

        key = (date_s, index_name)
        if key in seen:
            errors.append(f"Row {rn} | (date, index_name) | duplicate within file")
        else:
            seen.add(key)

        _validate_ohlc_row(rn, row, errors)

    return (len(errors) == 0), errors, df


def insert_index_prices(df):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for _, row in df.iterrows():
                iso_date = to_iso_date(row["date"])
                cur.execute(
                    """INSERT INTO index_prices (date, index_name, open, high, low, close)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON CONFLICT (date, index_name) DO UPDATE SET
                         open = EXCLUDED.open, high = EXCLUDED.high,
                         low = EXCLUDED.low, close = EXCLUDED.close""",
                    (iso_date, row["index_name"],
                     row["open"], row["high"], row["low"], row["close"]),
                )
            conn.commit()
        return True, f"Inserted/updated {len(df)} rows in index_prices.", len(df)
    except Exception as e:
        conn.rollback()
        return False, f"Database error: {e}", 0
    finally:
        conn.close()


# ============================================================
# DISPATCHER
# ============================================================

UPLOAD_HANDLERS = {
    "indexes_master":  (validate_indexes_master,  insert_indexes_master),
    "sectors_master":  (validate_sectors_master,  insert_sectors_master),
    "stocks_master":   (validate_stocks_master,   insert_stocks_master),
    "stock_prices":    (validate_stock_prices,    insert_stock_prices),
    "sector_prices":   (validate_sector_prices,   insert_sector_prices),
    "index_prices":    (validate_index_prices,    insert_index_prices),
}


def handle_upload(upload_type, file_storage):
    if upload_type not in UPLOAD_HANDLERS:
        return {"success": False, "errors": [f"Unknown upload type: {upload_type}"], "message": ""}

    df, parse_err = parse_file(file_storage)
    if parse_err:
        return {"success": False, "errors": [parse_err], "message": ""}

    if df is None or df.empty:
        return {"success": False, "errors": ["File is empty."], "message": ""}

    validator, inserter = UPLOAD_HANDLERS[upload_type]
    is_valid, errors, df_clean = validator(df)
    if not is_valid:
        return {"success": False, "errors": errors, "message": ""}

    success, message, rows = inserter(df_clean)
    if success:
        return {"success": True, "errors": [], "message": message, "rows": rows}
    return {"success": False, "errors": [message], "message": ""}


def get_table_counts():
    counts = {}
    for table in ["indexes_master", "sectors_master", "stocks_master",
                  "stock_prices", "sector_prices", "index_prices"]:
        rows = query_all(f"SELECT COUNT(*) AS c FROM {table}")
        counts[table] = rows[0]["c"] if rows else 0
    return counts
