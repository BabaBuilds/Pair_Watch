@echo off
cd /d "%~dp0"
where python >nul 2>nul
if %errorlevel%==0 (
  python watch.py --seed
  python watch.py --daemon
  goto :eof
)
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 watch.py --seed
  py -3 watch.py --daemon
  goto :eof
)
echo Python 3 not found. Install from https://www.python.org/downloads/
echo Check "Add Python to PATH" during setup, then run this again.
pause
