@echo off
rem Tablet away from home: lighter stream for internet upload (needs UDP 5600-5601 forwarded to this PC).
cd /d "%~dp0"
python wireless_cintiq.py --client android --monitor second --fps 30 --bitrate 6M %*
pause
