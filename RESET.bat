@echo off
title Stock Screener - Reset
cd /d "%~dp0"

echo ============================================================
echo   RESET - This will delete the venv folder and force
echo   a fresh setup the next time you run START.bat.
echo.
echo   Your database (PostgreSQL) is NOT touched by this.
echo ============================================================
echo.
set /p confirm="Type YES to confirm reset: "
if /i not "%confirm%"=="YES" (
    echo Cancelled.
    pause
    exit /b 0
)

if exist "venv" (
    echo Removing venv folder...
    rmdir /s /q venv
    echo Done.
) else (
    echo No venv folder found.
)

echo.
echo Reset complete. Run START.bat for a fresh setup.
pause
