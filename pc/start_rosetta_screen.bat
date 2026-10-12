@echo off
rem Tablet as a wireless second screen through the Rosetta Screen app (Android, hardware decoding).
cd /d "%~dp0"
python wireless_cintiq.py --client android --monitor second %*
pause
