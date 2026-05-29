import os
import time
import traceback
import requests
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
from chart_engine import create_all_charts

BOT_TOKEN = "8606697647:AAH0Qo1_a94a2Kd1Pn45QpEnw1tsTimmBuk"
CHAT_ID = "8132984888"

BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
MAX_ADAY = 10


def send_message(text):
    r = requests.post(
        f"{BASE_URL}/sendMessage",
        data={"chat_id": CHAT_ID, "text": str(text)[:3900]},
        timeout=30
    )
    print("TELEGRAM:", r.status_code, r.text[:300])

def save_signals_to_csv(adaylar):
    filename = "signals_history.csv"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows = []

    for a in adaylar:
        rows.append({
            "datetime": now,
            "symbol": a["symbol"],
            "score": a["score"],
            "price": a["price"],
            "rsi": a["rsi"],
            "rvol": a["rvol"],
            "reasons": " | ".join(a["reasons"])
        })

    df_new = pd.DataFrame(rows)

    if os.path.exists(filename):
        df_old = pd.read_csv(filename)
        df_all = pd.concat([df_old, df_new], ignore_index=True)
    else:
        df_all = df_new

    df_all.to_csv(filename, index=False)

def read_symbols():
    with open("symbols_bist.txt", "r", encoding="utf-8") as f:
        return [
            x.strip().upper().replace(".IS", "")
            for x in f.readlines()
            if x.strip() and not x.strip().startswith("#")
        ]


def get_data(symbol, interval, period):
    yf_symbol = f"{symbol}.IS"

    df = yf.download(
        yf_symbol,
        interval=interval,
        period=period,
        auto_adjust=False,
        progress=False,
        threads=False
    )

    if df.empty:
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.rename(columns={
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume"
    })

    df = df[["open", "high", "low", "close", "volume"]].dropna()

    if len(df) < 60:
        return None

    return df


def add_indicators(df):
    df = df.copy()
    c = df["close"]
    v = df["volume"]

    df["ema21"] = c.ewm(span=21, adjust=False).mean()
    df["ema50"] = c.ewm(span=50, adjust=False).mean()
    df["ema200"] = c.ewm(span=200, adjust=False).mean()

    delta = c.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    rs = gain.rolling(14).mean() / loss.rolling(14).mean()
    df["rsi"] = 100 - (100 / (1 + rs))

    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()

    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    direction = np.sign(c.diff()).fillna(0)
    df["obv"] = (direction * v).cumsum()
    df["obv_ma10"] = df["obv"].rolling(10).mean()

    df["vol_ma20"] = v.rolling(20).mean()
    df["rvol"] = v / df["vol_ma20"]

    return df.dropna()


def score_symbol(symbol):
    d15 = get_data(symbol, "15m", "60d")
    h1 = get_data(symbol, "60m", "730d")
    d1 = get_data(symbol, "1d", "2y")

    if d15 is None or h1 is None or d1 is None:
        return None

    d15 = add_indicators(d15)
    h1 = add_indicators(h1)
    d1 = add_indicators(d1)

    if d15.empty or h1.empty or d1.empty:
        return None

    a = d15.iloc[-1]
    ap = d15.iloc[-2]
    b = h1.iloc[-1]
    c = d1.iloc[-1]

    score = 0
    reasons = []

    if a["close"] > a["ema21"]:
        score += 10
        reasons.append("15dk EMA21 üstü")

    if a["ema21"] > a["ema50"]:
        score += 10
        reasons.append("15dk EMA21>EMA50")

    if a["rsi"] > 55:
        score += 10
        reasons.append("15dk RSI güçlü")

    if a["macd"] > a["macd_signal"]:
        score += 10
        reasons.append("15dk MACD pozitif")

    if a["macd_hist"] > ap["macd_hist"]:
        score += 5
        reasons.append("15dk momentum artıyor")

    if a["obv"] > a["obv_ma10"]:
        score += 10
        reasons.append("15dk OBV güçlü")

    if a["rvol"] > 1.5:
        score += 15
        reasons.append("15dk hacim patlaması")

    if b["close"] > b["ema21"]:
        score += 10
        reasons.append("1s EMA21 üstü")

    if b["ema21"] > b["ema50"]:
        score += 10
        reasons.append("1s trend pozitif")

    if c["close"] > c["ema50"]:
        score += 5
        reasons.append("Günlük EMA50 üstü")

    if c["close"] > c["ema200"]:
        score += 5
        reasons.append("Günlük EMA200 üstü")
    # ===== YENİ PATLAMA FİLTRELERİ =====

    # RSI yeni güçleniyor
    if 55 < a["rsi"] < 72:
        score += 10
        reasons.append("RSI sağlıklı güçleniyor")

    # Aşırı şişmiş RSI cezası
    if a["rsi"] > 85:
        score -= 15
        reasons.append("RSI aşırı şişmiş")

    # Yeni EMA kırılımı
    if (
        ap["close"] < ap["ema21"]
        and a["close"] > a["ema21"]
    ):
        score += 20
        reasons.append("EMA21 yeni kırıldı")

    # MACD yeni kesişim
    if (
        ap["macd"] < ap["macd_signal"]
        and a["macd"] > a["macd_signal"]
    ):
        score += 20
        reasons.append("MACD yeni AL verdi")

    # Hacim ivmesi
    if a["rvol"] > 2.5:
        score += 15
        reasons.append("Hacim ivmesi çok güçlü")

    # OBV sıçrama
    if (
        a["obv"] > a["obv_ma10"] * 1.02
    ):
        score += 10
        reasons.append("OBV para girişi güçlü")

    # Bollinger sıkışma sonrası genişleme
    bb_width_now = (
        d15["high"].rolling(20).mean().iloc[-1]
        - d15["low"].rolling(20).mean().iloc[-1]
    )

    bb_width_old = (
        d15["high"].rolling(20).mean().iloc[-5]
        - d15["low"].rolling(20).mean().iloc[-5]
    )

    if bb_width_now > bb_width_old * 1.2:
        score += 10
        reasons.append("Sıkışma sonrası genişleme")

    # Günlük trend desteği
    if c["ema21"] > c["ema50"]:
        score += 10
        reasons.append("Günlük trend güçlü")

    # Çok düşmüş tahtaları ele
    if a["close"] < a["ema200"]:
        score -= 20
        reasons.append("Uzun vadeli trend zayıf")
    return {
        "symbol": symbol,
        "score": score,
        "price": round(float(a["close"]), 2),
        "rsi": round(float(a["rsi"]), 2),
        "rvol": round(float(a["rvol"]), 2),
        "reasons": reasons
    }


def main():
    try:
        symbols = read_symbols()
        send_message(f"GOKHAN_BIST_RADAR_PRO başladı.\nTaranacak hisse sayısı: {len(symbols)}")

        results = []

        for i, symbol in enumerate(symbols, 1):
            try:
                item = score_symbol(symbol)
                if item:
                    results.append(item)
            except Exception as e:
                print(f"{symbol} hata: {e}")

            if i % 50 == 0:
                print(f"{i}/{len(symbols)} tarandı")

            time.sleep(0.15)

        results = sorted(results, key=lambda x: x["score"], reverse=True)
        adaylar = results[:MAX_ADAY]
        save_signals_to_csv(adaylar)
        
        if not adaylar:
            send_message("Tarama tamamlandı ancak uygun aday bulunamadı.")
            return

        msg = "📊 GOKHAN_BIST_RADAR_PRO\nEn güçlü adaylar:\n\n"

        for i, a in enumerate(adaylar, 1):
            msg += (
                f"{i}) {a['symbol']} | Skor: {a['score']}/100\n"
                f"Fiyat: {a['price']} | RSI15: {a['rsi']} | RVOL15: {a['rvol']}\n"
                f"Neden: {', '.join(a['reasons'][:7])}\n\n"
            )

       send_message(msg)

       send_message("İlk 3 aday için grafikler hazırlanıyor...")

       for a in adaylar[:3]:
       symbol = a["symbol"]
       send_message(f"{symbol} grafikleri hazırlanıyor...")

       files = create_all_charts(symbol)

       for file_path in files:
        send_photo(file_path)

       send_message(f"{symbol} grafik gönderimi tamamlandı.")

       send_message("Tarama tamamlandı.")

def send_photo(path):
    with open(path, "rb") as photo:
        r = requests.post(
            f"{BASE_URL}/sendPhoto",
            data={"chat_id": CHAT_ID},
            files={"photo": photo},
            timeout=90
        )
    print("TELEGRAM PHOTO:", r.status_code, r.text[:200])
    except Exception:
        send_message(traceback.format_exc())


if __name__ == "__main__":
    main()