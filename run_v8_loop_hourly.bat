@echo off
echo Gokhan BIST Radar V8 saatlik dongu basladi.
:loop
python bist_telegram_radar_v8.py
echo.
echo 1 saat bekleniyor...
timeout /t 3600 /nobreak
goto loop
