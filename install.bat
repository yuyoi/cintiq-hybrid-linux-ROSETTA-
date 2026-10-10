@echo off
cd /d "%~dp0"
where python >nul 2>nul || (echo Python 3.8 or newer is required: https://www.python.org/downloads/ & pause & exit /b 1)
python tools\install.py %*
echo.
pause
