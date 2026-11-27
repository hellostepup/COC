@echo off
REM One-time setup on Windows. Needs Python 3.9+ and Node.js 18+ on PATH.
cd /d %~dp0\..
python -m venv backend\.venv || goto :err
backend\.venv\Scripts\python -m pip install --upgrade pip
backend\.venv\Scripts\pip install -r backend\requirements.txt mss pytesseract || goto :err
cd frontend
call npm install || goto :err
call npm run build || goto :err
echo.
echo Setup done. Start the app with scripts\start_windows.bat
exit /b 0
:err
echo Setup failed.
exit /b 1
