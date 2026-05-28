import os
import time
import traceback
import requests
import yfinance as yf
import pandas as pd
import numpy as np

BOT_TOKEN = os.getenv("BOT_TOKEN", "8606697647:AAH0Qo1_a94a2Kd1Pn45QpEnw1tsTimmBuk")
CHAT_ID = os.getenv("CHAT_ID", "8132984888")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

MAX_ADAY = 10
MIN_GUNLUK_HACIM_TL = 25_000_000


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
    df["obv_slope"] = df["obv"].diff(5)

    df["vol_ma20"] = v.rolling(20).mean()
    df["rvol"] = v / df["vol_ma20"]

    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - c.shift()).abs(),
        (df["low"] - c.shift()).abs()
    ], axis=1).max(axis=1)

    df["atr"] = tr.rolling(14).mean()
    df["atr_pct"] = df["atr"] / c * 100

    return df.dropna()


def relative_strength(symbol_df, xu100_df):
    try:
        s_ret = symbol_df["close"].iloc[-1] / symbol_df["close"].iloc[-20] - 1
        x_ret = xu100_df["close"].iloc[-1] / xu100_df["close"].iloc[-20] - 1
        return s_ret - x_ret
    except Exception:
        return 0


def score_symbol(symbol, xu100_1d):
    d15 = get_data(symbol, "15m", "60d")
    h