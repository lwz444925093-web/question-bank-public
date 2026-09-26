@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
py -3.11 -c "import sys; sys.exit(0 if sys.maxsize > 2**32 else 1)" >nul 2>&1
if errorlevel 1 (
  echo Please install Python 3.11 x64 with Python Launcher first.
  echo See INSTALL.md or open install-guide.html.
  pause
  exit /b 1
)
py -3.11 -X utf8 scripts\windows_setup.py install
set result=%ERRORLEVEL%
pause
exit /b %result%
