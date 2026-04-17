@echo off
REM Setup script for TeamSlack PoC development environment

echo ===== TeamSlack Development Environment Setup =====
echo.

REM Change to project directory
cd /d "C:\Users\VIRNECT\Downloads\career\Private\TeamSlack"
echo Current directory: %cd%
echo.

REM Create virtual environment
echo [1/4] Creating Python virtual environment...
python.exe -m venv venv
if errorlevel 1 (
    echo ERROR: Failed to create virtual environment
    pause
    exit /b 1
)
echo Virtual environment created successfully
echo.

REM Activate virtual environment
echo [2/4] Activating virtual environment...
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo ERROR: Failed to activate virtual environment
    pause
    exit /b 1
)
echo Virtual environment activated
echo.

REM Upgrade pip
echo [3/4] Upgrading pip, setuptools, wheel...
python.exe -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
    echo ERROR: Failed to upgrade pip tools
    pause
    exit /b 1
)
echo pip tools upgraded successfully
echo.

REM Install requirements
echo [4/4] Installing project dependencies from requirements.txt...
pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: Failed to install requirements
    echo.
    echo Trying alternative installation method...
    pip install --no-cache-dir -r requirements.txt
    if errorlevel 1 (
        echo ERROR: Failed again. Check your internet connection and requirements.txt
        pause
        exit /b 1
    )
)
echo All dependencies installed successfully
echo.

REM Verify installation
echo [Verification] Checking installed packages...
pip list
echo.

echo ===== Setup Complete! =====
echo.
echo Next steps:
echo 1. Keep this terminal open or activate venv in new terminal with: venv\Scripts\activate.bat
echo 2. To run FastAPI app: python -m uvicorn apps.slack-bot.main:app --reload
echo 3. To run Celery worker: celery -A services.orchestrator.tasks worker --loglevel=info
echo.
echo For Docker setup:
echo - Install Docker Desktop from https://www.docker.com/products/docker-desktop
echo - Then run: docker-compose up -d
echo.
pause
