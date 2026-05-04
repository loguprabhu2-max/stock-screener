@echo off
setlocal EnableDelayedExpansion
title Stock Screener
color 0B

REM Move to the folder containing this script
cd /d "%~dp0"

echo.
echo ============================================================
echo   STOCK SCREENER - LAUNCHER
echo ============================================================
echo.

REM --- Step 1: Find Python ---
echo [1/6] Checking for Python...
set "PYTHON_CMD="
where python >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON_CMD=python"
) else (
    where py >nul 2>nul
    if !errorlevel!==0 (
        set "PYTHON_CMD=py"
    )
)

if not defined PYTHON_CMD (
    echo.
    echo ERROR: Python is not installed or not in PATH.
    echo Please install Python from https://www.python.org/downloads/
    echo and check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

%PYTHON_CMD% --version
echo.

REM --- Step 2: Check .env file ---
echo [2/6] Checking .env configuration...
if not exist ".env" (
    echo.
    echo .env file not found. Creating from .env.example ...
    copy ".env.example" ".env" >nul
    echo.
    echo ====================================================
    echo   IMPORTANT: Open the .env file in any text editor
    echo   and replace 'your_postgres_password_here'
    echo   with your actual PostgreSQL password.
    echo.
    echo   Also make sure you have created a database named
    echo   'stock_screener' in pgAdmin.
    echo ====================================================
    echo.
    echo Press any key to open .env now, then save it and re-run START.bat ...
    pause >nul
    notepad .env
    exit /b 0
)

REM Quick check that password was changed
findstr /C:"your_postgres_password_here" ".env" >nul
if %errorlevel%==0 (
    echo.
    echo ERROR: .env still contains the placeholder password.
    echo Please open .env in a text editor and replace
    echo 'your_postgres_password_here' with your real password.
    echo.
    notepad .env
    pause
    exit /b 1
)
echo .env looks ok.
echo.

REM --- Step 3: Create venv if needed ---
echo [3/6] Checking virtual environment...
if not exist "venv\Scripts\activate.bat" (
    echo Creating virtual environment ^(this may take a minute^)...
    %PYTHON_CMD% -m venv venv
    if %errorlevel% neq 0 (
        echo.
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo Virtual environment created.
) else (
    echo Virtual environment already exists.
)
echo.

REM --- Step 4: Activate venv ---
echo [4/6] Activating virtual environment...
call "venv\Scripts\activate.bat"
echo.

REM --- Step 5: Install packages if needed ---
echo [5/6] Checking Python packages...
if not exist "venv\.installed" (
    echo Installing packages ^(first run only, ~1-2 minutes^)...
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo.
        echo ============================================================
        echo   ERROR: Package installation failed.
        echo.
        echo   This often happens with very new Python versions.
        echo   If you are using Python 3.14, please install Python 3.12
        echo   from https://www.python.org/downloads/release/python-3128/
        echo.
        echo   After installing 3.12:
        echo     1. Delete the 'venv' folder
        echo     2. Run START.bat again
        echo ============================================================
        echo.
        pause
        exit /b 1
    )
    echo. > "venv\.installed"
    echo Packages installed.
) else (
    echo Packages already installed.
)
echo.

REM --- Step 6: Initialize database (first run only) ---
echo [6/6] Checking database setup...
if not exist "venv\.db_initialized" (
    echo Setting up database tables and admin user...
    cd backend
    python setup_db.py
    if %errorlevel% neq 0 (
        cd ..
        echo.
        echo ERROR: Database setup failed. See messages above.
        pause
        exit /b 1
    )
    cd ..
    echo. > "venv\.db_initialized"
) else (
    echo Database already initialized.
)
echo.

REM --- Launch website ---
echo ============================================================
echo   Starting website ...
echo   Open your browser:  http://localhost:5000
echo   Login:  admin  /  admin123
echo   Press Ctrl+C in this window to stop.
echo ============================================================
echo.

REM Open browser after a short delay
start "" /min cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:5000"

cd backend
python app.py

cd ..
echo.
echo Website stopped.
pause
