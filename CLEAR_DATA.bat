@echo off
title Stock Screener - Clear Data
cd /d "%~dp0"

echo ============================================================
echo   CLEAR ALL UPLOADED DATA
echo.
echo   This will DELETE all rows from these tables:
echo     - indexes_master
echo     - sectors_master
echo     - stocks_master
echo     - stock_prices
echo     - sector_prices
echo     - index_prices
echo.
echo   USERS table is NOT touched.
echo ============================================================
echo.
set /p confirm="Type CLEAR to confirm: "
if /i not "%confirm%"=="CLEAR" (
    echo Cancelled.
    pause
    exit /b 0
)

if not exist "venv\Scripts\activate.bat" (
    echo venv not found. Run START.bat first.
    pause
    exit /b 1
)

call "venv\Scripts\activate.bat"
cd backend
python -c "from database import execute; [execute(f'DELETE FROM {t}') for t in ['stock_prices','sector_prices','index_prices','stocks_master','sectors_master','indexes_master']]; print('All data cleared.')"
cd ..
echo.
pause
