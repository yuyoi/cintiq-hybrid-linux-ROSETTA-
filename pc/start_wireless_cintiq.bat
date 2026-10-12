@echo off
cd /d "%~dp0"
if "%TABLET_IP%"=="" set /p TABLET_IP=Tablet IP (Linux mode, see ip addr in its terminal): 
python wireless_cintiq.py --tablet-ip %TABLET_IP% %*
pause
