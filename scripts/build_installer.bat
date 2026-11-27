@echo off
REM Builds the Windows installer (.exe) into frontend\release.
REM Run setup_windows.bat first.
cd /d %~dp0\..\backend
.venv\Scripts\pip install pyinstaller || goto :err
.venv\Scripts\pyinstaller --noconfirm --name coc-backend --collect-submodules app --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.lifespan.on run.py || goto :err
cd ..\frontend
call npm run dist || goto :err
echo Installer built under frontend\release
exit /b 0
:err
echo Build failed.
exit /b 1
