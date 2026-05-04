# Stock Screener

A web-based stock screener built with Flask + PostgreSQL. Filter stocks, sectors, and indexes by date range and % return.

## Features

- 🔐 Login + role-based access (Admin / Normal user)
- 📈 Stock Screener — filter by index, sector, date range, % return
- 📊 Sector Screener — rank sectors by % return
- 📉 Index Screener — rank indexes by % return
- 📤 Admin upload — CSV / Excel files for OHLC data + masters
- 👥 User management (admin only)
- 📅 Smart calendar showing data availability
- 📥 Export results as CSV

## Tech stack

- Backend: Python + Flask + Flask-Login + Gunicorn
- Database: PostgreSQL (local or Supabase)
- Frontend: HTML + CSS + Lucide icons + Flatpickr
- Hosting: Render (free tier)

## Local development

1. Install Python 3.12 and PostgreSQL.
2. Create a database named `stock_screener` in pgAdmin.
3. Copy `.env.example` to `.env` and fill in your DB password.
4. Double-click `START.bat` (Windows). On first run it installs everything automatically.
5. Open http://localhost:5000 — login with `admin` / `admin123`.

## Deployment (Render + Supabase)

This project is configured for deployment to Render with Supabase as the database. See deployment guide.

Required environment variables on Render:
- `DATABASE_URL` — full Supabase connection string
- `SECRET_KEY` — long random string

## Default credentials

- Username: `admin`
- Password: `admin123`

⚠️ **Change immediately after first deployment.**
