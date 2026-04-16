@echo off
echo ========================================
echo  PDF to Audiobook - Quick Start
echo ========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.10+ from https://www.python.org/
    pause
    exit /b 1
)

REM Check if Node.js is installed
node --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js is not installed or not in PATH
    echo Please install Node.js 18+ from https://nodejs.org/
    pause
    exit /b 1
)

echo Starting backend server...
start "PDF to Audiobook Backend" cmd /k "cd backend && python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
timeout /t 3 >nul

echo Starting frontend dev server...
start "PDF to Audiobook Frontend" cmd /k "cd frontend && npm run dev"
timeout /t 2 >nul

echo.
echo ========================================
echo  Servers are starting...
echo ========================================
echo.
echo Backend API: http://localhost:8000
echo API Docs:    http://localhost:8000/docs
echo Frontend:    http://localhost:5173
echo.
echo Opening browser in 5 seconds...
timeout /t 5 >nul
start http://localhost:5173
echo.
echo Done! You can now use the application.
echo Press any key to exit this window...
pause >nul
