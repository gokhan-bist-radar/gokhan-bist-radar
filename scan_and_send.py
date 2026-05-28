import os
import time
import traceback
import requests
import yfinance as yf
import pandas as pd
import numpy as np

BOT_TOKEN = os.getenv("BOT_TOKEN", "BURAYA_BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID", "BURAYA_CHAT_ID")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

MAX_ADAY = 10
GRAFIK_ADAY = 3


def send_message(text):
    r = requests.post(
        f"{BASE_URL}/sendMessage",
        data={"chat_id": CHAT_ID, "text": str(text)[:3900]},
        timeout=30
    )
    print("Telegram:", r.status_code, r.text[:200])


def read_symbols():
    with open("symbols_bist.txt", "r", encoding="utf-8") as f:
        raw = f.read().splitlines()
    symbols = []
    for s in raw:
        s = s.strip().upper().replace(".IS", "")
        if s and not s.startswith("#"):
            symbols.append(s)
    return list(dict.fromkeys(symbols))


def get_data(symbol, interval, period):
    yf_symbol = symbol if symbol.endswith(".IS") else f"{symbol}.IS"
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
    return df if len(df) > 60 else None


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

    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - c.shift()).abs(),
        (df["low"] - c.shift()).abs()
    ], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14).mean()

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

    if len(d15) < 30 or len(h1) < 30 or len(d1) < 50:
        return None

    a = d15.iloc[-1]
    ap = d15.iloc[-2]
    b = h1.iloc[-1]
    c = d1.iloc[-1]

    score = 0
    reasons = []

    # 15 dk tetik
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

    # 1 saat onay
    if b["close"] > b["ema21"]:
        score += 10
        reasons.append("1s EMA21 üstü")
    if b["ema21"] > b["ema50"]:
        score += 10
        reasons.append("1s trend pozitif")
    if b["rsi"] > 50:
        score += 5
        reasons.append("1s RSI 50 üstü")

    # günlük filtre
    if c["close"] > c["ema50"]:
        score += 5
        reasons.append("Günlük EMA50 üstü")
    if c["close"] > c["ema200"]:
        score += 5
        reasons.append("Günlük EMA200 üstü")

    fiyat = round(float(a["close"]), 2)
    atr = float(a["atr"]) if pd.notna(a["atr"]) else 0
    stop = round(fiyat - 2 * atr, 2) if atr else None
    hedef = round(fiyat + 3 * atr, 2) if atr else None

    return {
        "symbol": symbol,
        "score": round(score, 1),
        "price": fiyat,
        "rsi15": round(float(a["rsi"]), 2),
        "rvol15": round(float(a["rvol"]), 2),
        "stop": stop,
        "target": hedef,
        "reasons": reasons[:8],
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

            if i % 25 == 0:
                print(f"{i}/{len(symbols)} tarandı")

            time.sleep(0.25)

        results = sorted(results, key=lambda x: x["score"], reverse=True)
        adaylar = results[:MAX_ADAY]

        if not adaylar:
            send_message("Tarama bitti ancak uygun aday bulunamadı.")
            return

        msg = "📊 GOKHAN_BIST_RADAR_PRO\n15dk tetik + 1s onay + günlük filtre\n\n"

        for idx, a in enumerate(adaylar, 1):
            msg += (
                f"{idx}) {a['symbol']} | Skor: {a['score']}/115\n"
                f"Fiyat: {a['price']} | RSI15: {a['rsi15']} | RVOL15: {a['rvol15']}\n"
                f"Stop: {a['stop']} | Hedef: {a['target']}\n"
                f"Neden: {', '.join(a['reasons'])}\n\n"
            )

        send_message(msg)

        send_message("Tarama tamamlandı. İlk aşama: sadece aday listesi gönderildi.")

    except Exception:
        send_message(traceback.format_exc())


if __name__ == "__main__":
    main()