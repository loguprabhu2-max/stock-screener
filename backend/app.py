"""Stock Screener - Main Flask application (final version)."""
import os
import csv
import io
import threading
import uuid
from pathlib import Path
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, Response, jsonify
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user,
)
from werkzeug.security import check_password_hash
from dotenv import load_dotenv

from database import query_one
from uploads import handle_upload, get_table_counts, UPLOAD_HANDLERS
from screeners import (
    parse_iso_date, fetch_filter_options,
    run_stock_screener, run_sector_screener, run_index_screener,
    get_available_dates, get_date_range,
)
from date_utils import format_display
import users as users_mod
from dashboard_stats import get_overview_stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND = PROJECT_ROOT / "frontend"

load_dotenv(PROJECT_ROOT / ".env")

app = Flask(
    __name__,
    template_folder=str(FRONTEND / "templates"),
    static_folder=str(FRONTEND / "static"),
)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-key-change-me")
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200 MB — supports lakh-scale CSV files

# In production, refuse to start with the default secret key
if os.getenv("RENDER") or os.getenv("FLASK_ENV") == "production":
    if app.config["SECRET_KEY"] == "dev-key-change-me":
        raise RuntimeError(
            "SECRET_KEY environment variable must be set in production. "
            "Generate one and add it to Render's environment variables."
        )

# Make date formatter available to all templates as {{ format_display(d) }}
app.jinja_env.globals["format_display"] = format_display

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to access this page."


class User(UserMixin):
    def __init__(self, user_id, username, role):
        self.id = user_id
        self.username = username
        self.role = role

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def is_co_admin(self):
        return self.role == "co_admin"

    @property
    def can_upload(self):
        # Admin and co_admin can both upload
        return self.role in ("admin", "co_admin")


@login_manager.user_loader
def load_user(user_id):
    row = query_one(
        "SELECT user_id, username, role FROM users WHERE user_id = %s",
        (user_id,),
    )
    if row:
        return User(row["user_id"], row["username"], row["role"])
    return None


def admin_required(f):
    @wraps(f)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_admin:
            flash("Admin access required.", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return wrapper


def upload_required(f):
    """Admin OR co_admin can access — both can upload."""
    @wraps(f)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.can_upload:
            flash("Upload access required.", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return wrapper


# ----------------- Auth -----------------
@app.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("Please enter both username and password.", "error")
            return render_template("login.html")

        row = query_one(
            "SELECT user_id, username, password_hash, role FROM users WHERE username = %s",
            (username,),
        )

        if row and check_password_hash(row["password_hash"], password):
            user = User(row["user_id"], row["username"], row["role"])
            login_user(user)
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "error")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    stats = get_overview_stats()
    return render_template("dashboard.html", stats=stats)


# ----------------- API: available dates for calendars -----------------
@app.route("/api/available-dates/<screener>")
@login_required
def api_available_dates(screener):
    table_map = {
        "stock": "stock_prices",
        "sector": "sector_prices",
        "index": "index_prices",
    }

    # Special case: union of all 3 price tables (used by Data Management)
    if screener == "all":
        all_dates = set()
        min_dates = []
        max_dates = []
        total = 0
        for t in ("stock_prices", "sector_prices", "index_prices"):
            ds = get_available_dates(t)
            all_dates.update(ds)
            r = get_date_range(t)
            if r["min"]:
                min_dates.append(r["min"])
                max_dates.append(r["max"])
            total += r["days"]
        sorted_dates = sorted(all_dates)
        if sorted_dates:
            return jsonify({
                "dates": sorted_dates,
                "range": {
                    "min": sorted_dates[0],
                    "max": sorted_dates[-1],
                    "days": len(sorted_dates),
                    "min_display": "",
                    "max_display": "",
                },
            })
        return jsonify({
            "dates": [],
            "range": {"min": None, "max": None, "days": 0,
                      "min_display": "", "max_display": ""},
        })

    if screener not in table_map:
        return jsonify({"error": "unknown screener"}), 400
    table = table_map[screener]
    return jsonify({
        "dates": get_available_dates(table),
        "range": get_date_range(table),
    })


# ----------------- Helpers for screeners -----------------
def _read_screener_form():
    """Parse common screener form fields. Returns (data_dict, errors_list)."""
    errors = []
    from_str = request.form.get("from_date", "").strip()
    to_str = request.form.get("to_date", "").strip()
    threshold_str = request.form.get("threshold", "").strip()

    from_date = parse_iso_date(from_str)
    to_date = parse_iso_date(to_str)

    if not from_str:
        errors.append("From Date is required.")
    elif not from_date:
        errors.append("From Date must be in YYYY-MM-DD format.")

    if not to_str:
        errors.append("To Date is required.")
    elif not to_date:
        errors.append("To Date must be in YYYY-MM-DD format.")

    if from_date and to_date and from_date > to_date:
        errors.append("From Date must be on or before To Date.")

    threshold = None
    if not threshold_str:
        errors.append("Threshold % is required.")
    else:
        try:
            threshold = float(threshold_str)
        except ValueError:
            errors.append("Threshold must be a number.")

    return {
        "from_date": from_date, "to_date": to_date, "threshold": threshold,
        "from_str": from_str, "to_str": to_str, "threshold_str": threshold_str,
    }, errors


# ----------------- Stock Screener -----------------
@app.route("/stock-screener", methods=["GET", "POST"])
@login_required
def stock_screener():
    options = fetch_filter_options()
    results = None
    info = None
    form_data = {
        "index_filter": "All",
        "sector_filter": "All",
        "from_str": "",
        "to_str": "",
        "threshold_str": "",
    }
    form_errors = []

    if request.method == "POST":
        form_data["index_filter"] = request.form.get("index_filter", "All")
        form_data["sector_filter"] = request.form.get("sector_filter", "All")

        parsed, form_errors = _read_screener_form()
        form_data["from_str"] = parsed["from_str"]
        form_data["to_str"] = parsed["to_str"]
        form_data["threshold_str"] = parsed["threshold_str"]

        if not form_errors:
            results, info = run_stock_screener(
                form_data["index_filter"],
                form_data["sector_filter"],
                parsed["from_date"],
                parsed["to_date"],
                parsed["threshold"],
            )

    return render_template(
        "stock_screener.html",
        options=options,
        results=results,
        info=info,
        form_data=form_data,
        form_errors=form_errors,
        date_range=get_date_range("stock_prices"),
    )


@app.route("/stock-screener/download", methods=["POST"])
@login_required
def stock_screener_download():
    parsed, errors = _read_screener_form()
    if errors:
        flash("Cannot download: " + "; ".join(errors), "error")
        return redirect(url_for("stock_screener"))

    index_filter = request.form.get("index_filter", "All")
    sector_filter = request.form.get("sector_filter", "All")
    results, _ = run_stock_screener(
        index_filter, sector_filter,
        parsed["from_date"], parsed["to_date"], parsed["threshold"],
    )

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Stock Symbol", "Stock Name", "Sector", "Indexes",
                     "Latest Date", "Latest Price", "% Return", "Avg Delivery %"])
    for r in results:
        writer.writerow([
            r["stock_symbol"], r["stock_name"], r["sector"], r["indexes"],
            r["latest_date"], r["latest_price"], r["return_pct"],
            r["avg_delivery_pct"] if r["avg_delivery_pct"] is not None else "",
        ])
    csv_data = out.getvalue()
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=stock_screener_results.csv"},
    )


# ----------------- Sector Screener -----------------
@app.route("/sector-screener", methods=["GET", "POST"])
@login_required
def sector_screener():
    results = None
    info = None
    form_data = {"from_str": "", "to_str": "", "threshold_str": ""}
    form_errors = []

    if request.method == "POST":
        parsed, form_errors = _read_screener_form()
        form_data["from_str"] = parsed["from_str"]
        form_data["to_str"] = parsed["to_str"]
        form_data["threshold_str"] = parsed["threshold_str"]

        if not form_errors:
            results, info = run_sector_screener(
                parsed["from_date"], parsed["to_date"], parsed["threshold"]
            )

    return render_template(
        "sector_screener.html",
        results=results, info=info,
        form_data=form_data, form_errors=form_errors,
        date_range=get_date_range("sector_prices"),
    )


@app.route("/sector-screener/download", methods=["POST"])
@login_required
def sector_screener_download():
    parsed, errors = _read_screener_form()
    if errors:
        flash("Cannot download: " + "; ".join(errors), "error")
        return redirect(url_for("sector_screener"))

    results, _ = run_sector_screener(parsed["from_date"], parsed["to_date"], parsed["threshold"])

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Sector Name", "Latest Date", "Latest Price", "% Return"])
    for r in results:
        writer.writerow([
            r["sector_name"], r["latest_date"], r["latest_price"], r["return_pct"],
        ])
    return Response(
        out.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=sector_screener_results.csv"},
    )


# ----------------- Index Screener -----------------
@app.route("/index-screener", methods=["GET", "POST"])
@login_required
def index_screener():
    results = None
    info = None
    form_data = {"from_str": "", "to_str": "", "threshold_str": ""}
    form_errors = []

    if request.method == "POST":
        parsed, form_errors = _read_screener_form()
        form_data["from_str"] = parsed["from_str"]
        form_data["to_str"] = parsed["to_str"]
        form_data["threshold_str"] = parsed["threshold_str"]

        if not form_errors:
            results, info = run_index_screener(
                parsed["from_date"], parsed["to_date"], parsed["threshold"]
            )

    return render_template(
        "index_screener.html",
        results=results, info=info,
        form_data=form_data, form_errors=form_errors,
        date_range=get_date_range("index_prices"),
    )


@app.route("/index-screener/download", methods=["POST"])
@login_required
def index_screener_download():
    parsed, errors = _read_screener_form()
    if errors:
        flash("Cannot download: " + "; ".join(errors), "error")
        return redirect(url_for("index_screener"))

    results, _ = run_index_screener(parsed["from_date"], parsed["to_date"], parsed["threshold"])

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Index Name", "Latest Date", "Latest Price", "% Return"])
    for r in results:
        writer.writerow([
            r["index_name"], r["latest_date"], r["latest_price"], r["return_pct"],
        ])
    return Response(
        out.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=index_screener_results.csv"},
    )


# ----------------- Upload (admin + co_admin) — async background processing -----------------

# In-memory job store: job_id -> {status, stage, progress, result}
# Jobs persist for the lifetime of the process; memory impact is negligible.
_jobs: dict = {}


def _run_upload_job(upload_type: str, file_bytes: bytes, filename: str, job_id: str) -> None:
    """Execute the upload pipeline in a background thread."""
    try:
        result = handle_upload(upload_type, file_bytes, filename, job_id=job_id, jobs=_jobs)
        _jobs[job_id].update({
            "status": "done",
            "result": result,
            "stage": "Complete",
            "progress": 100,
        })
    except Exception as exc:  # pragma: no cover
        _jobs[job_id].update({
            "status": "error",
            "result": {"success": False, "errors": [str(exc)], "message": "", "rows": 0},
            "stage": "Error",
            "progress": 0,
        })


@app.route("/upload", methods=["GET", "POST"])
@upload_required
def upload():
    if request.method == "POST":
        upload_type = request.form.get("upload_type", "")
        file = request.files.get("file")

        if not file or not file.filename:
            return jsonify({"error": "Please select a file to upload."}), 400

        if upload_type not in UPLOAD_HANDLERS:
            return jsonify({"error": f"Unknown upload type: {upload_type}"}), 400

        # Read file bytes in main thread — file stream is not thread-safe
        file_bytes = file.read()
        filename = file.filename

        job_id = str(uuid.uuid4())
        _jobs[job_id] = {"status": "processing", "stage": "Starting...", "progress": 2}

        t = threading.Thread(
            target=_run_upload_job,
            args=(upload_type, file_bytes, filename, job_id),
            daemon=True,
        )
        t.start()

        return jsonify({"job_id": job_id})

    counts = get_table_counts()
    return render_template("upload.html", counts=counts)


@app.route("/api/upload-status/<job_id>")
@login_required
def upload_job_status(job_id):
    """Polled by the frontend every 500 ms to get upload progress and result."""
    job = _jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


# ----------------- Data Management (admin only) -----------------
import data_management as dm


@app.route("/data-management", methods=["GET", "POST"])
@admin_required
def data_management():
    summary = dm.get_data_summary()
    preview = None
    delete_result = None

    if request.method == "POST":
        action = request.form.get("action", "")
        table = request.form.get("table", "")
        from_str = request.form.get("from_date", "").strip()
        to_str = request.form.get("to_date", "").strip()

        from_date = parse_iso_date(from_str)
        to_date = parse_iso_date(to_str)

        if not from_date or not to_date:
            flash("Both From Date and To Date are required.", "error")
            return redirect(url_for("data_management"))
        if from_date > to_date:
            flash("From Date must be on or before To Date.", "error")
            return redirect(url_for("data_management"))
        valid_tables = ["all"] + list(dm.TABLES.keys())
        if table not in valid_tables:
            flash("Please select a valid table.", "error")
            return redirect(url_for("data_management"))

        if action == "preview":
            preview = dm.count_rows_in_range(table, from_date, to_date)
            preview["table"] = table
            preview["from"] = from_str
            preview["to"] = to_str

        elif action == "delete":
            result = dm.delete_in_range(table, from_date, to_date)
            if "error" in result:
                flash(f"Error: {result['error']}", "error")
            else:
                flash(
                    f"Deleted {result['deleted']} rows. " + " | ".join(result["details"]),
                    "success",
                )
            return redirect(url_for("data_management"))

    return render_template(
        "data_management.html",
        summary=summary,
        preview=preview,
        tables=dm.TABLES,
    )


@app.route("/data-management/download", methods=["POST"])
@admin_required
def data_management_download():
    table = request.form.get("table", "")
    from_str = request.form.get("from_date", "").strip()
    to_str = request.form.get("to_date", "").strip()

    from_date = parse_iso_date(from_str)
    to_date = parse_iso_date(to_str)

    if not from_date or not to_date:
        flash("Both dates are required.", "error")
        return redirect(url_for("data_management"))
    if from_date > to_date:
        flash("From Date must be on or before To Date.", "error")
        return redirect(url_for("data_management"))

    if table == "all":
        zip_bytes = dm.export_all_as_zip(from_date, to_date)
        return Response(
            zip_bytes,
            mimetype="application/zip",
            headers={"Content-Disposition":
                     f"attachment; filename=all_data_{from_str}_to_{to_str}.zip"},
        )

    if table not in dm.TABLES:
        flash("Please select a valid table.", "error")
        return redirect(url_for("data_management"))

    csv_data = dm.export_csv(table, from_date, to_date)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition":
                 f"attachment; filename={table}_{from_str}_to_{to_str}.csv"},
    )


# ----------------- Manage Users (admin) -----------------
@app.route("/manage-users", methods=["GET", "POST"])
@admin_required
def manage_users():
    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "create":
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            role = request.form.get("role", "")
            ok, msg = users_mod.create_user(username, password, role)
            flash(msg, "success" if ok else "error")

        elif action == "delete":
            user_id = request.form.get("user_id", "")
            ok, msg = users_mod.delete_user(user_id, current_user.id)
            flash(msg, "success" if ok else "error")

        elif action == "reset_password":
            user_id = request.form.get("user_id", "")
            new_password = request.form.get("new_password", "")
            ok, msg = users_mod.reset_password(user_id, new_password)
            flash(msg, "success" if ok else "error")

        return redirect(url_for("manage_users"))

    user_list = users_mod.list_users()
    return render_template("manage_users.html", users=user_list)


if __name__ == "__main__":
    print("=" * 60)
    print("  Stock Screener is running!")
    print("  Open your browser to:  http://localhost:5000")
    print("  Login: admin / admin123")
    print("  Press Ctrl+C to stop.")
    print("=" * 60)
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)
