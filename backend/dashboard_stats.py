"""Dashboard overview stats. Pulled live from the database for the
Welcome page's stats strip."""
from database import query_one


def _format_size(bytes_value):
    """Human-friendly file size."""
    if not bytes_value:
        return "0 B"
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_value < 1024:
            return f"{bytes_value:.1f} {unit}".rstrip("0").rstrip(".") + (
                "" if unit == "B" else ""
            )
        bytes_value /= 1024
    return f"{bytes_value:.1f} TB"


def get_overview_stats():
    """Return counts + database size + most recent price date."""
    stats = {
        "total_stocks": 0,
        "total_sectors": 0,
        "total_indexes": 0,
        "data_size": "0 B",
        "last_updated": None,
    }

    try:
        r = query_one("SELECT COUNT(*) AS c FROM stocks_master")
        stats["total_stocks"] = r["c"] if r else 0

        r = query_one("SELECT COUNT(*) AS c FROM sectors_master")
        stats["total_sectors"] = r["c"] if r else 0

        r = query_one("SELECT COUNT(*) AS c FROM indexes_master")
        stats["total_indexes"] = r["c"] if r else 0

        # Approximate data size: sum of bytes used by price tables
        r = query_one("""
            SELECT
                pg_total_relation_size('stock_prices') +
                pg_total_relation_size('sector_prices') +
                pg_total_relation_size('index_prices') AS total_bytes
        """)
        if r and r["total_bytes"]:
            stats["data_size"] = _format_size(r["total_bytes"])

        # Last updated = max date across all 3 price tables
        r = query_one("""
            SELECT MAX(d) AS max_d FROM (
                SELECT MAX(date) AS d FROM stock_prices
                UNION ALL
                SELECT MAX(date) AS d FROM sector_prices
                UNION ALL
                SELECT MAX(date) AS d FROM index_prices
            ) t
        """)
        if r and r["max_d"]:
            stats["last_updated"] = r["max_d"]
    except Exception as e:
        # Tables may not exist yet; return zeros
        pass

    return stats
