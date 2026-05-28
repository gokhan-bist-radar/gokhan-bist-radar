import yfinance as yf
import pandas as pd
import ta
import requests
import time
BOT_TOKEN = "8606697647:AAH0Qo1_a94a2Kd1Pn45QpEnw1tsTimmBuk"
CHAT_ID = "8132984888"
symbols = [
    "THYAO.IS",
    "ASELS.IS",
    "EREGL.IS",
    "KCHOL.IS",
    "SISE.IS",
    "TUPRS.IS",
    "BIMAS.IS",
    "AKBNK.IS",
    "YKBNK.IS",
    "GARAN.IS"
]
def telegram_gonder(mesaj):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": mesaj
    })
sonuclar = []
for symbol in symbols:
    try:
        df = yf.download(
            symbol,
            period="3mo",
            interval="1d",
            progress=False,
            auto_adjust=True
        )
        if df.empty:
            print(f"{symbol} veri boş")
            continue
        close = df["Close"]
        ema20 = ta.trend.ema_indicator(close, window=20)
        ema50 = ta.trend.ema_indicator(close, window=50)
        rsi = ta.momentum.rsi(close, window=14)
        son_fiyat = float(close.iloc[-1])
        son_rsi = float(rsi.iloc[-1])
        ema20_son = float(ema20.iloc[-1])
        ema50_son = float(ema50.iloc[-1])
        hacim = df["Volume"].iloc[-1]
        hacim_ort = df["Volume"].tail(20).mean()
        skor = 0
        if son_fiyat > ema20_son:
            skor += 25
        if ema20_son > ema50_son:
            skor += 25
        if son_rsi > 55:
            skor += 25
        if hacim > hacim_ort * 1.5:
            skor += 25
        if skor >= 75:
            mesaj = f"""
🚀 GÜÇLÜ TARAMA
Hisse: {symbol}
Skor: {skor}/100
Fiyat: {round(son_fiyat,2)}
RSI: {round(son_rsi,2)}
EMA20: {round(ema20_son,2)}
EMA50: {round(ema50_son,2)}
Hacim Gücü: %{round((hacim/hacim_ort)*100,0)}
Durum:
• Trend güçlü
• Momentum güçlü
• Hacim artışı mevcut
"""
            telegram_gonder(mesaj)
            print(f"Gönderildi: {symbol}")
        time.sleep(1)
    except Exception as e:
        print(f"HATA {symbol}: {e}")
print("Tarama tamamlandı")