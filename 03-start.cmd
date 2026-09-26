@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist ".venv\Scripts\python.exe" (
  echo Please run 01-install.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -X utf8 scripts\windows_setup.py start
set result=%ERRORLEVEL%
pause
exit /b %result%
