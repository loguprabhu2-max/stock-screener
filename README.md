# Stock Screener — Offline (Local) Edition

A web-based stock screener that runs entirely on your laptop.
No internet, no cloud, no monthly costs.

## What you need installed

1. **Python 3.12** (recommended) — https://www.python.org/downloads/
   - During install, check ✅ **"Add Python to PATH"**
2. **PostgreSQL** with **pgAdmin** — https://www.postgresql.org/download/
   - Remember the password you set for the `postgres` user

## First-time setup (5 minutes)

### Step 1 — Create the database in pgAdmin
1. Open **pgAdmin**
2. Right-click **Databases** → **Create → Database…**
3. Name: `stock_screener` → Save

### Step 2 — Configure your password
1. Open the project folder
2. Open `.env.example` in Notepad
3. Replace `your_postgres_password_here` with your real Postgres password
4. **Save As** → name it exactly `.env` (with the dot at the start)

### Step 3 — First run
1. **Double-click `START.bat`**
2. It will automatically install Python packages, create database tables, and create the admin user
3. First run takes ~2 minutes (subsequent runs are instant)
4. Your browser opens to http://localhost:5000
5. Login: `admin` / `admin123`

### Step 4 — Upload your data
1. Click **Upload Data** in the sidebar
2. Upload in this order using files from `Excel format/` (samples) or your real data:
   - `indexes_master.csv` (1)
   - `sectors_master.csv` (2)
   - `stocks_master.csv` (3)
   - `stock_prices.csv` (4)
   - `sector_prices.csv` (5)
   - `index_prices.csv` (6)

## Day-to-day use

Just **double-click `START.bat`**. The website opens in your browser.
To stop: press Ctrl+C in the black window, or close it.

## Helper scripts

- `START.bat` — launch the website
- `RESET.bat` — wipe venv + re-install (keeps database)
- `CLEAR_DATA.bat` — wipe all price/master data (keeps users)

## Roles

- **Admin** — full access (screeners + upload + manage users + data management)
- **Co-admin** — screeners + upload only
- **Normal** — screeners only

Admin creates other users via the Manage Users page.
There is no self-signup.

## Default login

- Username: `admin`
- Password: `admin123`

Change this immediately on first login (Manage Users → Reset Password).

## Folder structure

```
website/
├── backend/                Python Flask code
│   ├── app.py
│   ├── database.py
│   ├── uploads.py
│   ├── screeners.py
│   ├── users.py
│   ├── data_management.py
│   ├── date_utils.py
│   └── setup_db.py
├── frontend/               HTML, CSS, JS
│   ├── templates/
│   └── static/
├── Excel format/           Sample CSVs to use as templates
├── .env                    Your password (you create this from .env.example)
├── .env.example
├── requirements.txt
├── schema.sql
├── START.bat               ← double-click to run
├── RESET.bat
└── CLEAR_DATA.bat
```

## Troubleshooting

**"Python not found"**
Python isn't installed or not in PATH. Reinstall from python.org and check "Add Python to PATH".

**"Database connection failed"**
- PostgreSQL service isn't running (open Services → Postgres → Start)
- Wrong password in `.env`
- Database `stock_screener` not created in pgAdmin

**"Package installation failed"**
Some packages don't have versions for very new Python (e.g. 3.14).
Install Python 3.12, then run `RESET.bat` and `START.bat` again.

**Site looks unstyled / icons missing**
Some features (Lucide icons, smart calendar) load from a CDN — they need internet.
Layout and functionality work fully offline, but icons may show as squares without internet.
For 100% offline icons, ask for the "self-contained" version.
