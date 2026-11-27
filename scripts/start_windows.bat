@echo off
REM Starts the desktop app (Electron starts the Python backend itself).
cd /d %~dp0\..\frontend
set ELECTRON_RUN_AS_NODE=
call npx electron .
