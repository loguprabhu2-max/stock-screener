"""Upload validators and DB writers for all 6 data files.

Performance design for lakh-scale uploads:
  - Validation uses vectorised pandas ops (.isin, pd.to_numeric, .duplicated) — 10-50x
    faster than row-by-row Python loops.
  - All inserts use psycopg2 execute_values — sends BATCH_SIZE rows per SQL round-trip
    instead of one INSERT per row. 40k rows: ~1s vs ~60s previously.
  - Date conversion done once as a pandas .apply() before building the row list.
  - Progress reported via the shared jobs dict so the frontend can poll.
  - Validation errors capped at MAX_ERRORS to prevent memory spikes on bad files.

Each upload type:
  1. Parses CSV/XLSX into a pandas DataFrame (parse_file).
  2. Runs fast vectorised validation — collects ALL errors up to cap, returns them.
  3. If errors → reject; otherwise bulk-inserts to DB with progress updates.
"""
import io
import pandas as pd
from psycopg2.extras import execute_values

from database import get_connection, query_all
from date_utils import parse_flexible_date

# Maximum validation errors reported before stopping (prevents RAM spike on huge bad files)
MAX_ERRORS = 50
# Rows per DB round-trip — tune higher for speed, lower for memory
BATCH_SIZE = 5_000


# ---------- Helpers ----------

def parse_file(file_bytes, filename):
    """Read raw bytes into a DataFrame. Returns (df, error_or_None)."""
    filename = (filename or "").lower()
    try:
        if filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(file_bytes), dtype=str, keep_default_na=False)
        elif filename.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(file_bytes), dtype=str, keep_default_na=False)
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


def excel_row_number(idx):
    """Convert 0-based DataFrame index → Excel row number."""
    return idx + 2


def _set_job_stage(jobs, job_id, stage, progress=None):
    """Thread-safe-enough update (CPython dict ops are atomic for simple writes)."""
    if job_id and jobs is not None:
        jobs[job_id]["stage"] = stage
        if progress is not None:
            jobs[job_id]["progress"] = progress


def _add_error(errors, msg):
    """Append error if below MAX_ERRORS cap. Returns True when cap is hit."""
    if len(errors) < MAX_ERRORS:
        errors.append(msg)
    return len(errors) >= MAX_ERRORS


def _bulk_insert(cur, sql, rows, job_id=None, jobs=None, base_progress=50):
    """Insert rows in BATCH_SIZE chunks with execute_values, updating progress."""
    total = len(rows)
    for i in range(0, total, BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        execute_values(cur, sql, batch, page_size=BATCH_SIZE)
        done = min(i + BATCH_SIZE, total)
        pct = base_progress + int((done / total) * 45)  # base_progress → base+45%
        _set_job_stage(jobs, job_id, f"Inserting rows {done:,} / {total:,}...", pct)


# ============================================================
# MASTER FILE VALIDATORS + INSERTERS
# ============================================================

def validate_indexes_master(df):
    errors = []
    errors += check_required_columns(df, ["index_name"])
    if errors:
        return False, errors, None

    empty_mask = df["index_name"].eq("")
    for idx in df.index[empty_mask]:
        if _add_error(errors, f"Row {excel_row_number(idx)} | index_name | empty value"):
            break

    dup_mask = df.duplicated(subset=["index_name"], keep="first")
    for idx in df.index[dup_mask]:
        if _add_error(errors, f"Row {excel_row_number(idx)} | index_name | duplicate '{df.at[idx, 'index_name']}'"):
            break

    return len(errors) == 0, errors, df


def insert_indexes_master(df, job_id=None, jobs=None):
    _set_job_stage(jobs, job_id, f"Inserting {len(df):,} rows into indexes_master...", 50)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM indexes_master")
            rows = list(zip(df["index_name"]))
            execute_values(cur, "INSERT INTO indexes_master (index_name) VALUES %s", rows)
            conn.commit()
        return True, f"Replaced indexes_master with {len(df):,} rows.", len(df)
    except Exception as e:
        conn.rollback()
        return False, f"Database error: {e}", 0
    finally:
        conn.close()


def validate_sectors_master(df):
    errors = []
    errors += check_required_columns(df, ["sector_name"])
    if errors:
        return False, errors, None

    empty_mask = df["sector_name"].eq("")
    for idx in df.index[empty_mask]:
        if _add_error(errors, f"Row {excel_row_number(idx)} | sector_name | empty value"):
            break

    dup_mask = df.duplicated(subset=["sector_name"], keep="first")
    for idx in df.index[dup_mask]:
        if _add_error(errors, f"Row {excel_row_number(idx)} | sector_name | duplicate '{df.at[idx, 'sector_name']}'"):
            break

    return len(errors) == 0, errors, df


def insert_sectors_master(df, job_id=None, jobs=None):
    _set_job_stage(jobs, job_id, f"Inserting {len(df):,} rows into sectors_master...", 50)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sectors_master")
            rows = list(zip(df["sector_name"]))
            execute_values(cur, "INSERT INTO sectors_master (sector_name) VALUES %s", rows)
            conn.commit()
        return True, f"Replaced sectors_master with {len(df):,} rows.", len(df)
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

    # Vectorised empty checks
    for col in ["stock_symbol", "stock_name", "sector", "indexes"]:
        empty_mask = df[col].eq("")
        for idx in df.index[empty_mask]:
            if _add_error(errors, f"Row {excel_row_number(idx)} | {col} | empty value"):
                return False, errors, None

    # Vectorised duplicate symbol check
    dup_mask = df.duplicated(subset=["stock_symbol"], keep="first")
    for idx in df.index[dup_mask]:
        if _add_error(errors, f"Row {excel_row_number(idx)} | stock_symbol | duplicate '{df.at[idx, 'stock_symbol']}'"):
            break

    # Validate comma-separated sector and index references (must stay row-by-row)
    for idx, row in df.iterrows():
        if len(errors) >= MAX_ERRORS:
            break
        rn = excel_row_number(idx)
        if row["sector"]:
            for sec in [x.strip() for x in row["sector"].split(",") if x.strip()]:
                if sec not in existing_sectors:
                    if _add_error(errors, f"Row {rn} | sector | '{sec}' not found in sectors_master"):
                        break
        if row["indexes"]:
            for ix in [x.strip() for x in row["indexes"].split(",") if x.strip()]:
                if ix not in existing_indexes:
                    if _add_error(errors, f"Row {rn} | indexes | '{ix}' not found in indexes_master"):
                        break

    return len(errors) == 0, errors, df


def insert_stocks_master(df, job_id=None, jobs=None):
    _set_job_stage(jobs, job_id, f"Inserting {len(df):,} rows into stocks_master...", 50)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM stocks_master")
            rows = list(zip(df["stock_symbol"], df["stock_name"], df["sector"], df["indexes"]))
            execute_values(
                cur,
                "INSERT INTO stocks_master (stock_symbol, stock_name, sector, indexes) VALUES %s",
                rows,
            )
            conn.commit()
        return True, f"Replaced stocks_master with {len(df):,} rows.", len(df)
    except Exception as e:
        conn.rollback()
        return False, f"Database error: {e}", 0
    finally:
        conn.close()


# ============================================================
# DAILY PRICE VALIDATORS + INSERTERS  (UPSERT on duplicate)
# ============================================================

# Numeric columns required in stock_prices uploads
STOCK_NUMERIC_COLS = [
    "open", "high", "low", "close",
    "total_trade_qty", "turnover_lakhs", "no_of_trades",
    "delivery_qty", "delivery_pct",
]
# Generic OHLC for sector/index
OHLC_COLS = ["open", "high", "low", "close"]


def _validate_price_common(df, key_col, valid_set, key_label, numeric_cols=None):
    """Shared vectorised validation for sector/index price files.
    Returns errors list (empty = valid)."""
    if numeric_cols is None:
        numeric_cols = OHLC_COLS
    errors = []

    # Date: empty
    empty_date = df["date"].eq("")
    for idx in df.index[empty_date]:
        if _add_error(errors, f"Row {excel_row_number(idx)} | date | empty value"):
            return errors

    # Date: invalid format
    bad_date = (~empty_date) & (~df["date"].apply(is_valid_date))
    for idx in df.index[bad_date]:
        if _add_error(errors,
                      f"Row {excel_row_number(idx)} | date | '{df.at[idx, 'date']}' is not a recognized date "
                      f"(try DD-MM-YYYY, DD/MM/YYYY, or YYYY-MM-DD)"):
            return errors

    # Key column: empty
    empty_key = df[key_col].eq("")
    for idx in df.index[empty_key]:
        if _add_error(errors, f"Row {excel_row_number(idx)} | {key_col} | empty value"):
            return errors

    # Key column: unknown value (vectorised .isin)
    bad_key = (~empty_key) & (~df[key_col].isin(valid_set))
    for idx in df.index[bad_key]:
        if _add_error(errors,
                      f"Row {excel_row_number(idx)} | {key_col} | '{df.at[idx, key_col]}' not found in {key_label}"):
            return errors

    # Duplicate composite key (vectorised .duplicated)
    dup_mask = df.duplicated(subset=["date", key_col], keep="first")
    for idx in df.index[dup_mask]:
        if _add_error(errors, f"Row {excel_row_number(idx)} | (date, {key_col}) | duplicate within file"):
            return errors

    # Numeric columns (vectorised pd.to_numeric)
    for col in numeric_cols:
        if len(errors) >= MAX_ERRORS:
            break
        bad_num = df[col].eq("") | pd.to_numeric(df[col], errors="coerce").isna()
        for idx in df.index[bad_num]:
            val = df.at[idx, col]
            msg = (f"Row {excel_row_number(idx)} | {col} | empty value"
                   if val == "" else
                   f"Row {excel_row_number(idx)} | {col} | '{val}' is not a number")
            if _add_error(errors, msg):
                break

    return errors


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

    # Date: empty
    empty_date = df["date"].eq("")
    for idx in df.index[empty_date]:
        if _add_error(errors, f"Row {excel_row_number(idx)} | date | empty value"):
            return False, errors, None

    # Date: invalid format
    bad_date = (~empty_date) & (~df["date"].apply(is_valid_date))
    for idx in df.index[bad_date]:
        if _add_error(errors,
                      f"Row {excel_row_number(idx)} | date | '{df.at[idx, 'date']}' is not a recognized date "
                      f"(try DD-MM-YYYY, DD/MM/YYYY, or YYYY-MM-DD)"):
            return False, errors, None

    # Symbol: empty
    empty_sym = df["stock_symbol"].eq("")
    for idx in df.index[empty_sym]:
        if _add_error(errors, f"Row {excel_row_number(idx)} | stock_symbol | empty value"):
            return False, errors, None

    # Symbol: unknown (vectorised .isin — very fast even on 1 lakh rows)
    bad_sym = (~empty_sym) & (~df["stock_symbol"].isin(valid_symbols))
    for idx in df.index[bad_sym]:
        if _add_error(errors,
                      f"Row {excel_row_number(idx)} | stock_symbol | '{df.at[idx, 'stock_symbol']}' not found in stocks_master"):
            return False, errors, None

    # Duplicate (date, stock_symbol) — vectorised .duplicated
    dup_mask = df.duplicated(subset=["date", "stock_symbol"], keep="first")
    for idx in df.index[dup_mask]:
        if _add_error(errors,
                      f"Row {excel_row_number(idx)} | (date, stock_symbol) | "
                      f"duplicate within file: {df.at[idx, 'date']}, {df.at[idx, 'stock_symbol']}"):
            break

    # All numeric columns — vectorised pd.to_numeric
    for col in STOCK_NUMERIC_COLS:
        if len(errors) >= MAX_ERRORS:
            break
        bad_num = df[col].eq("") | pd.to_numeric(df[col], errors="coerce").isna()
        for idx in df.index[bad_num]:
            val = df.at[idx, col]
            msg = (f"Row {excel_row_number(idx)} | {col} | empty value"
                   if val == "" else
                   f"Row {excel_row_number(idx)} | {col} | '{val}' is not a number")
            if _add_error(errors, msg):
                break

    return len(errors) == 0, errors, df


def insert_stock_prices(df, job_id=None, jobs=None):
    _set_job_stage(jobs, job_id, f"Converting {len(df):,} dates...", 47)

    # Vectorised date conversion (apply once, not inside the SQL loop)
    iso_dates = df["date"].apply(to_iso_date)

    # Build list of tuples using zip on Series — much faster than iterrows()
    rows = list(zip(
        iso_dates,
        df["stock_symbol"],
        df["open"], df["high"], df["low"], df["close"],
        df["total_trade_qty"], df["turnover_lakhs"], df["no_of_trades"],
        df["delivery_qty"], df["delivery_pct"],
    ))

    sql = """
        INSERT INTO stock_prices (
            date, stock_symbol, open, high, low, close,
            total_trade_qty, turnover_lakhs, no_of_trades,
            delivery_qty, delivery_pct
        ) VALUES %s
        ON CONFLICT (date, stock_symbol) DO UPDATE SET
            open             = EXCLUDED.open,
            high             = EXCLUDED.high,
            low              = EXCLUDED.low,
            close            = EXCLUDED.close,
            total_trade_qty  = EXCLUDED.total_trade_qty,
            turnover_lakhs   = EXCLUDED.turnover_lakhs,
            no_of_trades     = EXCLUDED.no_of_trades,
            delivery_qty     = EXCLUDED.delivery_qty,
            delivery_pct     = EXCLUDED.delivery_pct
    """

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            _bulk_insert(cur, sql, rows, job_id=job_id, jobs=jobs, base_progress=50)
            conn.commit()
        return True, f"Inserted/updated {len(df):,} rows in stock_prices.", len(df)
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

    errors = _validate_price_common(df, "sector_name", valid_sectors, "sectors_master")
    return len(errors) == 0, errors, df


def insert_sector_prices(df, job_id=None, jobs=None):
    _set_job_stage(jobs, job_id, f"Converting {len(df):,} dates...", 47)
    iso_dates = df["date"].apply(to_iso_date)
    rows = list(zip(iso_dates, df["sector_name"], df["open"], df["high"], df["low"], df["close"]))

    sql = """
        INSERT INTO sector_prices (date, sector_name, open, high, low, close)
        VALUES %s
        ON CONFLICT (date, sector_name) DO UPDATE SET
            open  = EXCLUDED.open,
            high  = EXCLUDED.high,
            low   = EXCLUDED.low,
            close = EXCLUDED.close
    """

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            _bulk_insert(cur, sql, rows, job_id=job_id, jobs=jobs, base_progress=50)
            conn.commit()
        return True, f"Inserted/updated {len(df):,} rows in sector_prices.", len(df)
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

    errors = _validate_price_common(df, "index_name", valid_indexes, "indexes_master")
    return len(errors) == 0, errors, df


def insert_index_prices(df, job_id=None, jobs=None):
    _set_job_stage(jobs, job_id, f"Converting {len(df):,} dates...", 47)
    iso_dates = df["date"].apply(to_iso_date)
    rows = list(zip(iso_dates, df["index_name"], df["open"], df["high"], df["low"], df["close"]))

    sql = """
        INSERT INTO index_prices (date, index_name, open, high, low, close)
        VALUES %s
        ON CONFLICT (date, index_name) DO UPDATE SET
            open  = EXCLUDED.open,
            high  = EXCLUDED.high,
            low   = EXCLUDED.low,
            close = EXCLUDED.close
    """

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            _bulk_insert(cur, sql, rows, job_id=job_id, jobs=jobs, base_progress=50)
            conn.commit()
        return True, f"Inserted/updated {len(df):,} rows in index_prices.", len(df)
    except Exception as e:
        conn.rollback()
        return False, f"Database error: {e}", 0
    finally:
        conn.close()


# ============================================================
# DISPATCHER
# ============================================================

def validate_future_daily(df):
    errors = []
    errors += check_required_columns(df, ["date", "future_index", "stock_symbol", "open", "high", "low", "close"])
    if errors:
        return False, errors, None

    # Date empty
    empty_date = df["date"].eq("")
    for idx in df.index[empty_date]:
        if _add_error(errors, f"Row {excel_row_number(idx)} | date | empty value"):
            return False, errors, None

    # Date invalid
    bad_date = (~empty_date) & (~df["date"].apply(is_valid_date))
    for idx in df.index[bad_date]:
        if _add_error(errors, f"Row {excel_row_number(idx)} | date | '{df.at[idx, 'date']}' is not a recognized date"):
            return False, errors, None

    # future_index empty
    empty_fi = df["future_index"].eq("")
    for idx in df.index[empty_fi]:
        if _add_error(errors, f"Row {excel_row_number(idx)} | future_index | empty value"):
            return False, errors, None

    # stock_symbol empty
    empty_sym = df["stock_symbol"].eq("")
    for idx in df.index[empty_sym]:
        if _add_error(errors, f"Row {excel_row_number(idx)} | stock_symbol | empty value"):
            return False, errors, None

    # Numeric columns
    for col in OHLC_COLS:
        if len(errors) >= MAX_ERRORS:
            break
        bad_num = df[col].eq("") | pd.to_numeric(df[col], errors="coerce").isna()
        for idx in df.index[bad_num]:
            val = df.at[idx, col]
            msg = (f"Row {excel_row_number(idx)} | {col} | empty value"
                   if val == "" else
                   f"Row {excel_row_number(idx)} | {col} | '{val}' is not a number")
            if _add_error(errors, msg):
                break

    return len(errors) == 0, errors, df


def insert_future_daily(df, job_id=None, jobs=None):
    _set_job_stage(jobs, job_id, f"Converting {len(df):,} dates...", 47)
    iso_dates = df["date"].apply(to_iso_date)
    rows = list(zip(iso_dates, df["future_index"], df["stock_symbol"],
                    df["open"], df["high"], df["low"], df["close"]))

    sql = """
        INSERT INTO future_daily (date, future_index, stock_symbol, open, high, low, close)
        VALUES %s
        ON CONFLICT (date, future_index, stock_symbol) DO UPDATE SET
            open  = EXCLUDED.open,
            high  = EXCLUDED.high,
            low   = EXCLUDED.low,
            close = EXCLUDED.close
    """

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            _bulk_insert(cur, sql, rows, job_id=job_id, jobs=jobs, base_progress=50)
            conn.commit()
        return True, f"Inserted/updated {len(df):,} rows in future_daily.", len(df)
    except Exception as e:
        conn.rollback()
        return False, f"Database error: {e}", 0
    finally:
        conn.close()


UPLOAD_HANDLERS = {
    "indexes_master": (validate_indexes_master, insert_indexes_master),
    "sectors_master": (validate_sectors_master, insert_sectors_master),
    "stocks_master":  (validate_stocks_master,  insert_stocks_master),
    "stock_prices":   (validate_stock_prices,   insert_stock_prices),
    "sector_prices":  (validate_sector_prices,  insert_sector_prices),
    "index_prices":   (validate_index_prices,   insert_index_prices),
    "future_daily":   (validate_future_daily,   insert_future_daily),
}


def handle_upload(upload_type, file_bytes, filename, job_id=None, jobs=None):
    """Main entry point for file uploads. Returns result dict.

    Args:
        upload_type: one of the UPLOAD_HANDLERS keys
        file_bytes:  raw file content (bytes) — read from request before thread
        filename:    original filename for extension detection
        job_id:      optional job ID for progress tracking
        jobs:        optional shared dict updated with stage/progress info
    """

    def _stage(stage, pct=None):
        _set_job_stage(jobs, job_id, stage, pct)

    if upload_type not in UPLOAD_HANDLERS:
        return {"success": False, "errors": [f"Unknown upload type: {upload_type}"], "message": ""}

    _stage("Reading file...", 5)
    df, parse_err = parse_file(file_bytes, filename)
    if parse_err:
        return {"success": False, "errors": [parse_err], "message": ""}
    if df is None or df.empty:
        return {"success": False, "errors": ["File is empty."], "message": ""}

    _stage(f"Validating {len(df):,} rows...", 20)
    validator, inserter = UPLOAD_HANDLERS[upload_type]
    is_valid, errors, df_clean = validator(df)

    if not is_valid:
        if len(errors) >= MAX_ERRORS:
            errors.append(f"⚠ Showing first {MAX_ERRORS} errors — fix these and re-upload.")
        return {"success": False, "errors": errors, "message": "", "rows": 0}

    _stage(f"Inserting {len(df_clean):,} rows into database...", 45)
    success, message, rows = inserter(df_clean, job_id=job_id, jobs=jobs)

    if success:
        return {"success": True, "errors": [], "message": message, "rows": rows}
    return {"success": False, "errors": [message], "message": ""}


def get_table_counts():
    counts = {}
    for table in ["indexes_master", "sectors_master", "stocks_master",
                  "stock_prices", "sector_prices", "index_prices", "future_daily"]:
        rows = query_all(f"SELECT COUNT(*) AS c FROM {table}")
        counts[table] = rows[0]["c"] if rows else 0
    return counts
