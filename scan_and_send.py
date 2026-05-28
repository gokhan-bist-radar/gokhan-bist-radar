import os
import requests
import traceback
import pandas as pd

from data_provider import get_data
from indicators import add_indicators
from chart_engine import create_all_charts


BOT_TOKEN = os.getenv("BOT_TOKEN", "BURAYA_BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID", "BURAYA_CHAT_ID")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

MAX_ADAY = 5


def send_message(text):
    requests.post(
        f"{BASE_URL}/sendMessage",
        data={"chat_id": CHAT_ID, "text": str(text)[:3900]},
        timeout=30,
    )


def send_photo(path):
    with open(path, "rb") as photo:
        requests.post(
            f"{BASE_URL}/sendPhoto",
            data={"chat_id": CHAT_ID},
            files={"photo": photo},
            timeout=90,
        )


def read_symbols():
    with open("symbols_bist.txt", "r", encoding="utf-8") as f:
        symbols = [x.strip().upper().replace(".IS", "") for x in f.readlines()]
    return [s for s in symbols if s and not s.startswith("#")]


def score_symbol(symbol):
    df = get_data(symbol, "1d")
    df = add_indicators(df)

    if len(df) < 220:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]

    score = 0
    reasons = []

    close = last["close"]

    if close > last["ema21"]:
        score += 10
        reasons.append("EMA21 üstü")

    if close > last["ema50"]:
        score += 10
        reasons.append("EMA50 üstü")

    if last["ema21"] > last["ema50"]:
        score += 10
        reasons.append("EMA21>EMA50")

    if last["rsi"] > 50:
        score += 10
        reasons.append("RSI 50 üstü")

    if last["rsi"] > prev["rsi"]:
        score += 5
        reasons.append("RSI yükseliyor")

    if last["macd"] > last["macd_signal"]:
        score += 15
        reasons.append("MACD pozitif")

    if last["macd_hist"] > prev["macd_hist"]:
        score += 5
        reasons.append("MACD güçleniyor")

    if last["obv"] > df["obv"].rolling(10).mean().iloc[-1]:
        score += 15
        reasons.append("OBV güçlü")

    if last["relative_volume"] > 1.5:
        score += 15
        reasons.append("Hacim patlaması")

    if close > last["bb_mid"]:
        score += 5
        reasons.append("Bollinger orta üstü")

    atr = last["atr"]
    stop = round(close - 2 * atr, 2) if pd.notna(atr) else None
    hedef = round(close + 2 * atr, 2) if pd.notna(atr) else None

    return {
        "symbol": symbol,
        "score": round(score, 1),
        "close": round(close, 2),
        "rsi": round(last["rsi"], 2) if pd.notna(last["rsi"]) else None,
        "rv": round(last["relative_volume"], 2) if pd.notna(last["relative_volume"]) else None,
        "stop": stop,
        "hedef": hedef,
        "reasons": reasons,
    }


def main():
    try:
        send_message("GOKHAN_BIST_RADAR_PRO gerçek BIST taraması başladı.")

        symbols = read_symbols()
        results = []

        for i, symbol in enumerate(symbols, start=1):
            try:
                item = score_symbol(symbol)
                if item:
                    results.append(item)
            except Exception as e:
                print(f"{symbol} hata: {e}")

        results = sorted(results, key=lambda x: x["score"], reverse=True)
        adaylar = results[:MAX_ADAY]

        if not adaylar:
            send_message("Tarama sonucunda uygun aday bulunamadı.")
            return

        mesaj = "TARAMA SONUCU EN GÜÇLÜ ADAYLAR:\n\n"

        for idx, a in enumerate(adaylar, start=1):
            mesaj += (
                f"{idx}) {a['symbol']} | Skor: {a['score']}\n"
                f"Fiyat: {a['close']} | RSI: {a['rsi']} | RVOL: {a['rv']}\n"
                f"Stop: {a['stop']} | Hedef: {a['hedef']}\n"
                f"Neden: {', '.join(a['reasons'])}\n\n"
            )

        send_message(mesaj)

        for a in adaylar:
            symbol = a["symbol"]
            send_message(f"{symbol} için 5 zaman dilimli grafik hazırlanıyor...")

            files = create_all_charts(symbol)

            if not files:
                send_message(f"{symbol} için grafik oluşturulamadı.")
                continue

            for file_path in files:
                send_photo(file_path)

            send_message(f"{symbol} grafik gönderimi tamamlandı.")

        send_message("Gerçek BIST taraması tamamlandı.")

    except Exception:
        send_message(traceback.format_exc())


if __name__ == "__main__":
    main()