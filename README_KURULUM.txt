GÖKHAN BIST RADAR V8 TELEGRAM

Bu sürüm aynı Wi-Fi istemez. Program PC, VPS veya GitHub Actions üzerinde çalışır; tarama bitince Telegram'a özet mesaj ve grafik yollar.

NE YAPAR?
- BIST listesini tarar.
- 1 saatlik, 4 saatlik ve günlük zamanı birlikte değerlendirir.
- “Gidenleri” değil, “gitmek üzere olanları” bulmaya odaklanır.
- EMA8/21/50, RSI, MACD, OBV, hacim, sıkışma, dirence yakınlık ve RSI uyumsuzluğu kullanır.
- Telegram'a önce puanlı özet mesaj yollar.
- En iyi adaylar için 1H + 4H + 1D grafik gönderir.
- Grafiklerde fiyat/EMA, RSI, MACD ve OBV panelleri vardır.

KURULUM
1) Python kur.
2) install.bat çalıştır.
3) Telegram bot oluştur:
   - Telegram'da @BotFather
   - /newbot
   - Token al.
4) Chat ID bul:
   - Botuna “merhaba” yaz.
   - Tarayıcıda aç:
     https://api.telegram.org/botTOKEN/getUpdates
   - chat id değerini al.
5) config.json dosyasına token ve chat_id yaz.
6) run_v8_once.bat çalıştır.

SÜREKLİ ÇALIŞMA
- PC açık kalacaksa: run_v8_loop_hourly.bat
- VPS/cloud varsa aynı dosyayı kullanabilirsin.
- GitHub Actions örneği .github/workflows/bist-radar.yml içinde var.
