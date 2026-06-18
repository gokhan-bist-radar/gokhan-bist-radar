# -*- coding: utf-8 -*-
"""
SANAL_GOKHAN_BIST_RADAR_V13

V9.1 üzerine temiz revizyon:
- Mevcut çalışan yapı korunmuştur:
  config.json, symbols_file, manual_takas.csv, Telegram, grafik gönderimi, chart_engine bağlantısı
- Yeni eklenenler:
  15dk / 1s / 4s / 1g kırılım hesabı
  ATR bazlı stop ve hedef
  Trend temelli Fibonacci 0.618 / 1.000 / 1.272 / 1.618 / 2.000
  Risk/ödül oranı
  Kırılım ve Fibonacci skoru
  Telegram özetinde kırılım + fib bilgisi
  CSV çıktılarında yeni alanlar

Yatırım tavsiyesi değildir. Teknik tarama ve karar destek aracıdır.
"""

import datetime as dt
import json
import os
import time
import traceback
from zoneinfo import ZoneInfo
import urllib.parse
import urllib.request
from pathlib import Path
import csv
from pathlib import Path
from collections import Counter
import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
from chart_engine import create_all_charts  # V9.1 uyumluluğu için korunmuştur.

OUT = Path("outputs")
CHARTS = OUT / "charts"
OUT.mkdir(exist_ok=True)
CHARTS.mkdir(exist_ok=True)
MEMORY_FILE = Path("radar_memory.csv")
SIGNALS_FILE = Path("radar_signals.csv")

# ============================================================
# CONFIG / SYMBOL
# ============================================================

def load_config():
    return json.loads(Path("config.json").read_text(encoding="utf-8"))


def load_symbols(path):
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        x = line.strip().upper()
        if x and not x.startswith("#"):
            out.append(x[:-3] if x.endswith(".IS") else x)
    return sorted(set(out))


# ============================================================
# TEMEL İNDİKATÖRLER
# ============================================================

def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def rsi(s, n=14):
    d = s.diff()
    gain = d.clip(lower=0)
    loss = -d.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/n, min_periods=n, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/n, min_periods=n, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50)


def atr(df, n=14):
    pc = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - pc).abs(),
        (df["Low"] - pc).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def macd(close, fast=12, slow=26, signal=9):
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    hist = line - sig
    return line, sig, hist


def obv(close, volume):
    return (np.sign(close.diff()).fillna(0) * volume).cumsum()


def mfi(df, n=14):
    typical = (df["High"] + df["Low"] + df["Close"]) / 3
    flow = typical * df["Volume"]
    direction = np.sign(typical.diff()).fillna(0)
    pos = flow.where(direction > 0, 0).rolling(n).sum()
    neg = flow.where(direction < 0, 0).rolling(n).sum().abs()
    ratio = pos / neg.replace(0, np.nan)
    return (100 - (100 / (1 + ratio))).fillna(50)


def cmf(df, n=20):
    denom = (df["High"] - df["Low"]).replace(0, np.nan)
    mfm = ((df["Close"] - df["Low"]) - (df["High"] - df["Close"])) / denom
    mfv = mfm.fillna(0) * df["Volume"]
    return (mfv.rolling(n).sum() / df["Volume"].rolling(n).sum()).fillna(0)


def download(symbol, period, interval):
    try:
        df = yf.download(
            symbol,
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=False
        )

        print(f"DEBUG {symbol} -> columns={list(df.columns) if df is not None else 'NONE'}")

        if df is None or df.empty:
            print(f"DEBUG EMPTY: {symbol}")
            return None

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]

        print(f"DEBUG FIXED {symbol} -> columns={list(df.columns)}")

        df = df.dropna().copy()

        required = ["Open", "High", "Low", "Close", "Volume"]

        for c in required:
            if c not in df.columns:
                print(f"DEBUG MISSING COLUMN {symbol}: {c}")
                return None

        print(f"DEBUG OK DATA {symbol}: rows={len(df)}")

        return df

    except Exception as e:
        print(f"DEBUG DOWNLOAD ERROR {symbol}: {e}")
        return None


def resample_intraday(df, rule):
    if df is None or df.empty:
        return None
    out = df.resample(rule).agg({
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum"
    }).dropna()
    return out if len(out) > 50 else None


def add_ind(df):
    df = df.copy()
    df["EMA8"] = ema(df["Close"], 8)
    df["EMA21"] = ema(df["Close"], 21)
    df["EMA50"] = ema(df["Close"], 50)
    df["EMA200"] = ema(df["Close"], 200)
    df["RSI14"] = rsi(df["Close"])
    df["ATR14"] = atr(df)
    df["MACD"], df["MACD_SIGNAL"], df["MACD_HIST"] = macd(df["Close"])
    df["OBV"] = obv(df["Close"], df["Volume"])
    df["OBV_EMA10"] = ema(df["OBV"], 10)
    df["MFI14"] = mfi(df)
    df["CMF20"] = cmf(df)
    df["VOL_AVG20"] = df["Volume"].rolling(20).mean()
    df["VALUE_TL"] = df["Close"] * df["Volume"]
    df["VALUE_AVG20_TL"] = df["VALUE_TL"].rolling(20).mean()
    df["RES10"] = df["High"].rolling(10).max()
    df["RES20"] = df["High"].rolling(20).max()
    df["SUP20"] = df["Low"].rolling(20).min()
    df["RET_1"] = df["Close"].pct_change(1) * 100
    df["RET_5"] = df["Close"].pct_change(5) * 100
    df["RET_20"] = df["Close"].pct_change(20) * 100
    df["RANGE10_PCT"] = ((df["High"].rolling(10).max() - df["Low"].rolling(10).min()) / df["Close"]) * 100
    df["UPPER_WICK_PCT"] = ((df["High"] - df[["Open", "Close"]].max(axis=1)) / df["Close"]) * 100
    return df


# ============================================================
# PIVOT / UYUMSUZLUK
# ============================================================

def pivots(series, order=3, kind="low"):
    vals = series.values
    out = []
    for i in range(order, len(vals) - order):
        w = vals[i-order:i+order+1]
        if kind == "low" and vals[i] == np.nanmin(w):
            out.append(i)
        elif kind == "high" and vals[i] == np.nanmax(w):
            out.append(i)
    return out


def rsi_divergence(df, lookback=60):
    d = df.tail(lookback)
    if len(d) < 25:
        return "YOK"

    lows = pivots(d["Low"], 3, "low")
    highs = pivots(d["High"], 3, "high")

    if len(lows) >= 2:
        a, b = lows[-2], lows[-1]
        if d["Low"].iloc[b] < d["Low"].iloc[a] and d["RSI14"].iloc[b] > d["RSI14"].iloc[a]:
            return "POZITIF"

    if len(highs) >= 2:
        a, b = highs[-2], highs[-1]
        if d["High"].iloc[b] > d["High"].iloc[a] and d["RSI14"].iloc[b] < d["RSI14"].iloc[a]:
            return "NEGATIF"

    return "YOK"


def indicator_divergence(df, indicator_col, lookback=60):
    d = df.tail(lookback)
    if len(d) < 25 or indicator_col not in d.columns:
        return "YOK"

    lows = pivots(d["Low"], 3, "low")
    highs = pivots(d["High"], 3, "high")

    if len(lows) >= 2:
        a, b = lows[-2], lows[-1]
        if d["Low"].iloc[b] < d["Low"].iloc[a] and d[indicator_col].iloc[b] > d[indicator_col].iloc[a]:
            return "POZITIF"

    if len(highs) >= 2:
        a, b = highs[-2], highs[-1]
        if d["High"].iloc[b] > d["High"].iloc[a] and d[indicator_col].iloc[b] < d[indicator_col].iloc[a]:
            return "NEGATIF"

    return "YOK"


def all_divergences(df, lookback=60):
    return {
        "rsi": rsi_divergence(df, lookback),
        "macd": indicator_divergence(df, "MACD_HIST", lookback),
        "obv": indicator_divergence(df, "OBV", lookback),
        "mfi": indicator_divergence(df, "MFI14", lookback),
    }


# ============================================================
# YENİ MODÜL: KIRILIM + FIBONACCI
# ============================================================

def breakout_targets(df, lookback=20, atr_mult_1=1.0, atr_mult_2=2.0):
    """
    Kırılım hesabı:
    - Kırılım: son lookback mumun bir önceki kapanmış mumlara göre direnci
    - Stop: EMA21 ve destekten daha temkinli olan seviye
    - Hedef: kırılım + ATR katsayısı
    """
    if df is None or len(df) < max(lookback + 5, 40):
        return empty_breakout()

    d = df.copy()
    r = d.iloc[-1]

    prev_window = d.iloc[-lookback-1:-1]
    if prev_window.empty:
        return empty_breakout()

    close = float(r["Close"])
    atr14 = float(r["ATR14"]) if not pd.isna(r["ATR14"]) else 0.0

    breakout = float(prev_window["High"].max())
    support = float(prev_window["Low"].min())
    ema21 = float(r["EMA21"]) if not pd.isna(r["EMA21"]) else support

    # V10.3: Kırılım işleminde stop, çok uzak destek yerine pratik ATR tamponlu EMA/destek mantığıyla kurulur.
    ema_buffer_stop = ema21 - (atr14 * 0.20)
    stop = max(support, ema_buffer_stop)

    # Stop fiyatın üstüne taşarsa güvenli tarafta kalıp desteğe döneriz.
    if stop >= close:
        stop = support

    target_1 = breakout + atr14 * atr_mult_1
    target_2 = breakout + atr14 * atr_mult_2

    risk = close - stop
    reward = target_1 - close
    rr = reward / risk if risk > 0 else None

    distance_pct = ((breakout - close) / close) * 100 if close > 0 else None
    is_breakout = close > breakout
    near_breakout = distance_pct is not None and -1.0 <= distance_pct <= 3.0

    return {
        "breakout": round(breakout, 2),
        "support": round(support, 2),
        "stop_breakout": round(stop, 2),
        "target_1": round(target_1, 2),
        "target_2": round(target_2, 2),
        "risk_reward": round(rr, 2) if rr is not None else None,
        "distance_pct": round(distance_pct, 2) if distance_pct is not None else None,
        "is_breakout": bool(is_breakout),
        "near_breakout": bool(near_breakout)
    }


def empty_breakout():
    return {
        "breakout": None,
        "support": None,
        "stop_breakout": None,
        "target_1": None,
        "target_2": None,
        "risk_reward": None,
        "distance_pct": None,
        "is_breakout": False,
        "near_breakout": False
    }


def trend_fib_levels(df, lookback=120):
    """
    Trend temelli Fibonacci:
    Son pivot high öncesindeki son pivot low alınır.
    Yükselen trend uzatma hedefleri hesaplanır.
    Ayrıca 0.618 geri çekilme desteği verilir.
    """
    if df is None or len(df) < 50:
        return empty_fib()

    d = df.tail(lookback).copy()
    lows = pivots(d["Low"], 3, "low")
    highs = pivots(d["High"], 3, "high")

    if not lows or not highs:
        return empty_fib()

    high_i = highs[-1]
    low_candidates = [i for i in lows if i < high_i]
    if not low_candidates:
        return empty_fib()

    low_i = low_candidates[-1]
    low = float(d["Low"].iloc[low_i])
    high = float(d["High"].iloc[high_i])
    close = float(d["Close"].iloc[-1])

    if high <= low:
        return empty_fib()

    diff = high - low

    fib_0618 = high - diff * 0.618
    fib_1000 = high
    fib_1272 = high + diff * 0.272
    fib_1618 = high + diff * 0.618
    fib_2000 = high + diff * 1.000

    if close < fib_0618:
        pos = "0.618 altı / zayıf"
    elif fib_0618 <= close <= fib_1000:
        pos = "0.618-1.000 arası / sağlıklı trend"
    elif fib_1000 < close <= fib_1618:
        pos = "1.000-1.618 arası / hedef bölgesi"
    else:
        pos = "1.618 üstü / uzamış"

    return {
        "fib_low": round(low, 2),
        "fib_high": round(high, 2),
        "fib_0618": round(fib_0618, 2),
        "fib_1000": round(fib_1000, 2),
        "fib_1272": round(fib_1272, 2),
        "fib_1618": round(fib_1618, 2),
        "fib_2000": round(fib_2000, 2),
        "fib_position": pos
    }


def empty_fib():
    return {
        "fib_low": None,
        "fib_high": None,
        "fib_0618": None,
        "fib_1000": None,
        "fib_1272": None,
        "fib_1618": None,
        "fib_2000": None,
        "fib_position": "Hesaplanamadı"
    }


def setup_targets_for_df(df):
    return {
        "breakout": breakout_targets(df),
        "fib": trend_fib_levels(df)
    }


def target_score(setup):
    """
    Kırılım ve hedef kalite skoru.
    0-25 arası.
    """
    b = setup["breakout"]
    f = setup["fib"]

    score = 0
    notes = []
    flags = []

    if b["near_breakout"]:
        score += 6
        notes.append("kırılıma yakın")
    if b["is_breakout"]:
        score += 8
        notes.append("kırılım gerçekleşmiş")

    rr = b["risk_reward"]
    if rr is not None:
        if rr >= 2:
            score += 6
            notes.append("R/R güçlü")
        elif rr >= 1.5:
            score += 4
            notes.append("R/R kabul")
        elif rr < 1:
            score -= 4
            flags.append("R/R zayıf")

    if f["fib_position"] == "0.618-1.000 arası / sağlıklı trend":
        score += 5
        notes.append("Fib sağlıklı trend")
    elif f["fib_position"] == "1.000-1.618 arası / hedef bölgesi":
        score += 3
        notes.append("Fib hedef bölgesi")
    elif f["fib_position"] == "1.618 üstü / uzamış":
        score -= 5
        flags.append("Fib uzamış")

    return max(-10, min(25, int(score))), " | ".join(notes), " | ".join(flags)


# ============================================================
# PİYASA / TAKAS / PARA AKIŞI
# ============================================================

def market_bonus(index_df):
    if index_df is None or len(index_df) < 220:
        return 0, "Bilinmiyor"

    r = index_df.iloc[-1]
    score = 0

    if r["Close"] > r["EMA21"]:
        score += 1
    if r["EMA21"] > r["EMA50"]:
        score += 1
    if r["Close"] > r["EMA200"]:
        score += 1
    if r["RSI14"] > 45:
        score += 1
    if r["RET_20"] > 0:
        score += 1

    if score >= 4:
        return 8, "Pozitif"
    if score == 3:
        return 3, "Nötr+"
    if score == 2:
        return -5, "Yatay/Riskli"
    return -15, "Negatif"


def load_takas():
    p = Path("manual_takas.csv")
    if not p.exists():
        return {}

    df = pd.read_csv(p)
    out = {}

    for _, r in df.iterrows():
        sym = str(r.get("symbol", "")).upper().replace(".IS", "")
        out[sym] = r.to_dict()

    return out


def takas_score(sym, takas_map):
    r = takas_map.get(sym.replace(".IS", ""), {})
    if not r:
        return 0, "Takas veri yok"

    score = 0
    notes = []

    for key, pts, name in [
        ("fund_net_change_pct", 8, "Fon artışı"),
        ("foreign_net_change_pct", 6, "Yabancı artışı"),
        ("top5_net_change_pct", 5, "İlk 5 kurum alımı")
    ]:
        try:
            val = float(r.get(key, 0) or 0)
        except Exception:
            val = 0

        if val > 2:
            score += pts
            notes.append(name)
        elif val < -2:
            score -= pts
            notes.append(name + " negatif")

    return max(-20, min(20, score)), " | ".join(notes) if notes else "Takas nötr"


def money_flow_score(df, volume_mult=1.8):
    r = df.iloc[-1]
    prev = df.iloc[-2]
    score = 0
    notes = []

    if r["OBV"] > r["OBV_EMA10"]:
        score += 20
        notes.append("OBV pozitif")

    if len(df) > 12 and df["OBV"].iloc[-1] > df["OBV"].iloc[-10]:
        score += 15
        notes.append("OBV trend yukarı")

    if r["CMF20"] > 0.08:
        score += 20
        notes.append("CMF para girişi")
    elif r["CMF20"] > 0:
        score += 10
        notes.append("CMF pozitif")

    if 55 < r["MFI14"] < 80:
        score += 15
        notes.append("MFI güçlü")

    if r["VOL_AVG20"] and r["Volume"] > r["VOL_AVG20"] * volume_mult and r["Close"] > r["Open"]:
        score += 20
        notes.append("Yeşil hacim patlaması")

    if r["MACD_HIST"] > prev["MACD_HIST"] and r["MACD_HIST"] > 0:
        score += 10
        notes.append("MACD para momentumu")

    return max(0, min(100, int(score))), " | ".join(notes)


# ============================================================
# RS XU100 / GÖRECELİ GÜÇ
# ============================================================

def relative_strength_vs_index(stock_df, index_df, lookback=20):
    if stock_df is None or index_df is None:
        return None
    if len(stock_df) < lookback + 2 or len(index_df) < lookback + 2:
        return None

    s = stock_df["Close"].tail(lookback + 1)
    i = index_df["Close"].tail(lookback + 1)

    stock_ret = (s.iloc[-1] / s.iloc[0] - 1) * 100
    index_ret = (i.iloc[-1] / i.iloc[0] - 1) * 100

    return round(float(stock_ret - index_ret), 2)


# ============================================================
# TIMEFRAME SKORU
# ============================================================

def tf_score(df, min_value_tl, bonus=0, volume_mult=1.8):
    if df is None or len(df) < 70:
        return 0, {}, "Veri yok"

    r = df.iloc[-1]
    prev = df.iloc[-2]
    score = 0
    notes = []
    flags = []

    if r["EMA8"] > r["EMA21"]:
        score += 12
        notes.append("EMA8>21")
    if r["EMA21"] >= r["EMA50"] * 0.995:
        score += 10
        notes.append("EMA21/50 yakın")
    if r["Close"] > r["EMA8"]:
        score += 8
        notes.append("Fiyat EMA8 üstü")
    if r["MACD_HIST"] > prev["MACD_HIST"]:
        score += 13
        notes.append("MACD hist artıyor")
    if r["MACD"] > r["MACD_SIGNAL"]:
        score += 10
        notes.append("MACD pozitif")
    if r["OBV"] > r["OBV_EMA10"]:
        score += 10
        notes.append("OBV pozitif")
    if r["VOL_AVG20"] and r["Volume"] > r["VOL_AVG20"] * 1.3:
        score += 10
        notes.append("Hacim kıpırdanıyor")
    if 48 <= r["RSI14"] <= 66:
        score += 10
        notes.append("RSI uygun")
    if r["Close"] >= df["RES10"].iloc[-2] * 0.985:
        score += 9
        notes.append("Dirence yakın")
    if r["RANGE10_PCT"] <= 6.8:
        score += 8
        notes.append("Sıkışma")

    divs = all_divergences(df)
    div = divs["rsi"]

    if divs["rsi"] == "POZITIF":
        score += 10
        notes.append("RSI pozitif uyumsuzluk")
    elif divs["rsi"] == "NEGATIF":
        score -= 14
        flags.append("RSI negatif uyumsuzluk")

    if divs["macd"] == "POZITIF":
        score += 6
        notes.append("MACD pozitif uyumsuzluk")
    elif divs["macd"] == "NEGATIF":
        score -= 10
        flags.append("MACD negatif uyumsuzluk")

    if divs["obv"] == "POZITIF":
        score += 8
        notes.append("OBV pozitif uyumsuzluk")
    elif divs["obv"] == "NEGATIF":
        score -= 18
        flags.append("OBV negatif uyumsuzluk")

    if divs["mfi"] == "POZITIF":
        score += 5
        notes.append("MFI pozitif uyumsuzluk")
    elif divs["mfi"] == "NEGATIF":
        score -= 8
        flags.append("MFI negatif uyumsuzluk")

    if r["VALUE_AVG20_TL"] < min_value_tl:
        score -= 15
        flags.append("Likidite zayıf")
    if r["RSI14"] > 74:
        score -= 12
        flags.append("RSI sıcak")
    if r["RET_1"] > 8.5:
        score -= 15
        flags.append("Zaten gitmiş olabilir")
    if r["UPPER_WICK_PCT"] > 5:
        score -= 8
        flags.append("Üst fitil")

    mf_score, mf_note = money_flow_score(df, volume_mult)
    if mf_score >= 65:
        score += 12
        notes.append("Güçlü para girişi")
    elif mf_score >= 45:
        score += 6
        notes.append("Para girişi orta")

    setup = setup_targets_for_df(df)
    t_score, t_notes, t_flags = target_score(setup)
    score += t_score

    if t_notes:
        notes.append(t_notes)
    if t_flags:
        flags.append(t_flags)

    score += bonus

    state = {
        "close": round(float(r["Close"]), 2),
        "rsi": round(float(r["RSI14"]), 2),
        "mfi": round(float(r["MFI14"]), 2),
        "cmf": round(float(r["CMF20"]), 4),
        "macd_hist": round(float(r["MACD_HIST"]), 4),
        "obv_ok": bool(r["OBV"] > r["OBV_EMA10"]),
        "volume_ratio": round(float(r["Volume"] / r["VOL_AVG20"]), 2) if r["VOL_AVG20"] else None,
        "divergence": div,
        "div_rsi": divs["rsi"],
        "div_macd": divs["macd"],
        "div_obv": divs["obv"],
        "div_mfi": divs["mfi"],
        "money_flow_score": mf_score,
        "money_flow_note": mf_note,
        "notes": " | ".join(notes),
        "flags": " | ".join(flags),
        "support": round(float(r["SUP20"]), 2),
        "resistance": round(float(r["RES20"]), 2),
        "stop": round(float(r["Close"] - 1.5 * r["ATR14"]), 2) if not pd.isna(r["ATR14"]) else None,
        "target": round(float(r["Close"] + 2.0 * r["ATR14"]), 2) if not pd.isna(r["ATR14"]) else None,
        "breakout": setup["breakout"],
        "fib": setup["fib"],
        "target_score": t_score,
        "target_note": t_notes,
        "target_flags": t_flags,
    }

    return max(0, min(125, int(score))), state, " | ".join(notes + flags)


def empty_state():
    return {
        "close": None,
        "rsi": None,
        "mfi": None,
        "cmf": None,
        "macd_hist": None,
        "obv_ok": None,
        "volume_ratio": None,
        "divergence": "YOK",
        "div_rsi": "YOK",
        "div_macd": "YOK",
        "div_obv": "YOK",
        "div_mfi": "YOK",
        "money_flow_score": 0,
        "money_flow_note": "Veri yok",
        "notes": "",
        "flags": "Veri yok",
        "support": None,
        "resistance": None,
        "stop": None,
        "target": None,
        "breakout": empty_breakout(),
        "fib": empty_fib(),
        "target_score": 0,
        "target_note": "",
        "target_flags": ""
    }


# ============================================================
# HİSSE ANALİZİ
# ============================================================

def analyze_symbol(sym, cfg, mkt_bonus, takas_map, index_df=None):
    y = sym + ".IS"

    d1_raw = download(y, cfg["period_daily"], "1d")
    if d1_raw is None or len(d1_raw) < 120:
        return None
    d1 = add_ind(d1_raw)

    m15 = None
    h1 = None
    h4 = None
    available_tfs = ["1D"]

    m15_raw = download(y, "30d", "15m")
    if m15_raw is not None and len(m15_raw) >= 80:
        m15 = add_ind(m15_raw)
        h1_raw = resample_intraday(m15_raw, "1h")
        h4_raw = resample_intraday(m15_raw, "4h")

        if h1_raw is not None and len(h1_raw) >= 50:
            h1 = add_ind(h1_raw)
        if h4_raw is not None and len(h4_raw) >= 30:
            h4 = add_ind(h4_raw)

        available_tfs.insert(0, "15M")

    if h1 is None:
        h1_raw_direct = download(y, cfg.get("period_intraday", "60d"), "1h")
        if h1_raw_direct is not None and len(h1_raw_direct) >= 70:
            h1 = add_ind(h1_raw_direct)
            h4_raw = resample_intraday(h1_raw_direct, "4h")
            if h4_raw is not None and len(h4_raw) >= 30:
                h4 = add_ind(h4_raw)
            available_tfs.insert(0, "1H")

    if h4 is not None and "4H" not in available_tfs:
        available_tfs.insert(0, "4H")

    s15, st15 = 0, empty_state()
    s1h, st1h = 0, empty_state()
    s4h, st4h = 0, empty_state()

    if m15 is not None:
        s15, st15, _ = tf_score(m15, cfg["min_avg_value_TL"], 0, cfg["strong_volume_multiplier"])
    if h1 is not None:
        s1h, st1h, _ = tf_score(h1, cfg["min_avg_value_TL"], 0, cfg["strong_volume_multiplier"])
    if h4 is not None:
        s4h, st4h, _ = tf_score(h4, cfg["min_avg_value_TL"], 0, cfg["strong_volume_multiplier"])

    s1d, st1d, _ = tf_score(d1, cfg["min_avg_value_TL"], mkt_bonus, cfg["strong_volume_multiplier"])
    ts, tn = takas_score(y, takas_map)

    rs_xu100_20 = relative_strength_vs_index(d1, index_df, 20)
    rs_xu100_60 = relative_strength_vs_index(d1, index_df, 60)

    rs_bonus = 0
    rs_notes = []

    if rs_xu100_20 is not None:
        if rs_xu100_20 >= 10:
            rs_bonus += 8
            rs_notes.append("RS20 çok güçlü")
        elif rs_xu100_20 >= 3:
            rs_bonus += 4
            rs_notes.append("RS20 güçlü")
        elif rs_xu100_20 < -5:
            rs_bonus -= 8
            rs_notes.append("RS20 zayıf")

    if rs_xu100_60 is not None:
        if rs_xu100_60 >= 15:
            rs_bonus += 7
            rs_notes.append("RS60 lider")
        elif rs_xu100_60 >= 5:
            rs_bonus += 3
            rs_notes.append("RS60 güçlü")
        elif rs_xu100_60 < -8:
            rs_bonus -= 7
            rs_notes.append("RS60 zayıf")

    # Dinamik ağırlık korunmuştur. V11'de RS XU100 bonus/cezası son toplam skora eklenir.
    if m15 is not None and h1 is not None and h4 is not None:
        total = int(round(s15 * 0.32 + s1h * 0.28 + s4h * 0.25 + s1d * 0.15 + ts * 0.30))
    elif h1 is not None and h4 is not None:
        total = int(round(s1h * 0.45 + s4h * 0.35 + s1d * 0.20 + ts * 0.30))
    elif h1 is not None:
        total = int(round(s1h * 0.65 + s1d * 0.35 + ts * 0.30))
    else:
        total = int(round(s1d + ts * 0.30))

    total = int(round(total + rs_bonus))

    status = (
        "PATLAMA ADAYI" if total >= cfg["early_score_threshold"]
        else "YAKIN İZLE" if total >= cfg["early_score_threshold"] - 10
        else "BEKLE"
    )

    setup = []
    if s15 >= 70:
        setup.append("15dk tetik")
    if s1h >= 70:
        setup.append("1s onay")
    if s4h >= 70:
        setup.append("4s kurulum")
    if s1d >= 65:
        setup.append("günlük destek")

    if st15["money_flow_score"] >= cfg["strong_money_flow_threshold"]:
        setup.append("15dk güçlü para girişi")
    elif st1h["money_flow_score"] >= cfg["strong_money_flow_threshold"]:
        setup.append("1s güçlü para girişi")

    if st15["divergence"] == "POZITIF" or st1h["divergence"] == "POZITIF":
        setup.append("RSI pozitif uyumsuzluk")

    if st15["breakout"]["near_breakout"] or st15["breakout"]["is_breakout"]:
        setup.append("15dk kırılım bölgesi")

    if st15["fib"]["fib_position"] in ["0.618-1.000 arası / sağlıklı trend", "1.000-1.618 arası / hedef bölgesi"]:
        setup.append("15dk Fib uyumlu")

    if ts > 0:
        setup.append("takas pozitif")

    if rs_notes:
        setup.append(" + ".join(rs_notes))

    setup.append("veri:" + ",".join(available_tfs))

    frames = {"1D": d1}
    if h4 is not None:
        frames["4H"] = h4
    if h1 is not None:
        frames["1H"] = h1
    if m15 is not None:
        frames["15M"] = m15

    # Ana hedef bilgisi: 15M varsa 15M, yoksa 1H, yoksa 1D.
    primary_state = st15 if m15 is not None else st1h if h1 is not None else st1d

    return {
        "symbol": y,
        "score": total,
        "status": status,
        "setup": " + ".join(setup) if setup else "erken/zayıf kurulum",
        "close": st1d["close"],

        "score_15m": s15,
        "score_1h": s1h,
        "score_4h": s4h,
        "score_1d": s1d,

        "rsi_15m": st15["rsi"],
        "rsi_1h": st1h["rsi"],
        "rsi_4h": st4h["rsi"],
        "rsi_1d": st1d["rsi"],

        "div_15m": st15["divergence"],
        "div_1h": st1h["divergence"],
        "div_4h": st4h["divergence"],
        "div_1d": st1d["divergence"],

        "div_obv_15m": st15["div_obv"],
        "div_obv_1h": st1h["div_obv"],
        "div_macd_15m": st15["div_macd"],
        "div_macd_1h": st1h["div_macd"],
        "div_mfi_15m": st15["div_mfi"],
        "div_mfi_1h": st1h["div_mfi"],

        "money_flow_15m": st15["money_flow_score"],
        "money_flow_1h": st1h["money_flow_score"],
        "money_flow_4h": st4h["money_flow_score"],
        "money_flow_1d": st1d["money_flow_score"],
        "money_flow_note_15m": st15["money_flow_note"],

        "vol_15m": st15["volume_ratio"],
        "vol_1h": st1h["volume_ratio"],
        "vol_4h": st4h["volume_ratio"],
        "vol_1d": st1d["volume_ratio"],

        "takas_score": ts,
        "takas_note": tn,

        "rs_xu100_20": rs_xu100_20,
        "rs_xu100_60": rs_xu100_60,
        "rs_note": " | ".join(rs_notes),

        "support": st1d["support"],
        "resistance": st1d["resistance"],
        "stop": st1d["stop"],
        "target": st1d["target"],

        "breakout_level": primary_state["breakout"]["breakout"],
        "breakout_distance_pct": primary_state["breakout"]["distance_pct"],
        "breakout_stop": primary_state["breakout"]["stop_breakout"],
        "breakout_target_1": primary_state["breakout"]["target_1"],
        "breakout_target_2": primary_state["breakout"]["target_2"],
        "risk_reward": primary_state["breakout"]["risk_reward"],
        "is_breakout": primary_state["breakout"]["is_breakout"],
        "near_breakout": primary_state["breakout"]["near_breakout"],

        "fib_low": primary_state["fib"]["fib_low"],
        "fib_high": primary_state["fib"]["fib_high"],
        "fib_0618": primary_state["fib"]["fib_0618"],
        "fib_1000": primary_state["fib"]["fib_1000"],
        "fib_1272": primary_state["fib"]["fib_1272"],
        "fib_1618": primary_state["fib"]["fib_1618"],
        "fib_2000": primary_state["fib"]["fib_2000"],
        "fib_position": primary_state["fib"]["fib_position"],

        "risk_flags": " | ".join([
            x for x in [st15.get("flags"), st1h.get("flags"), st4h.get("flags"), st1d.get("flags")]
            if x and x != "Veri yok"
        ]),

        "available_tfs": ",".join(available_tfs),
        "_frames": frames
    }


# ============================================================
# GRAFİK
# ============================================================

def plot_timeframe_chart(result, tf, cfg):
    sym = result["symbol"].replace(".IS", "")
    df = result["_frames"][tf].tail(140)
    path = CHARTS / f"{sym}_{tf.lower()}_chart.png"

    plt.style.use("dark_background")
    fig = plt.figure(figsize=(12, 10))
    fig.suptitle(f"{sym} | {tf} | Skor {result['score']} | {result['status']}", fontsize=14)

    axp = fig.add_subplot(4, 1, 1)
    axr = fig.add_subplot(4, 1, 2, sharex=axp)
    axm = fig.add_subplot(4, 1, 3, sharex=axp)
    axo = fig.add_subplot(4, 1, 4, sharex=axp)

    axp.plot(df.index, df["Close"], label="Fiyat", linewidth=1.4)
    axp.plot(df.index, df["EMA8"], label="EMA8", linewidth=1.0)
    axp.plot(df.index, df["EMA21"], label="EMA21", linewidth=1.0)
    axp.plot(df.index, df["EMA50"], label="EMA50", linewidth=1.0)

    setup = setup_targets_for_df(df)
    b = setup["breakout"]
    f = setup["fib"]

    if b["breakout"] is not None:
        axp.axhline(b["breakout"], linestyle="--", linewidth=.9, label="Kırılım")
    if b["stop_breakout"] is not None:
        axp.axhline(b["stop_breakout"], linestyle="--", linewidth=.9, label="Stop")
    if b["target_1"] is not None:
        axp.axhline(b["target_1"], linestyle=":", linewidth=.9, label="Hedef 1")
    if b["target_2"] is not None:
        axp.axhline(b["target_2"], linestyle=":", linewidth=.9, label="Hedef 2")

    if f["fib_0618"] is not None:
        axp.axhline(f["fib_0618"], linestyle="-.", linewidth=.8, label="Fib 0.618")
        axp.axhline(f["fib_1618"], linestyle="-.", linewidth=.8, label="Fib 1.618")

    axp.grid(alpha=.22)
    axp.legend(fontsize=8)

    axr.plot(df.index, df["RSI14"], label="RSI14", linewidth=1.1)
    axr.axhline(70, linestyle="--", linewidth=.8)
    axr.axhline(50, linestyle="--", linewidth=.8)
    axr.axhline(30, linestyle="--", linewidth=.8)
    axr.grid(alpha=.22)
    axr.legend(fontsize=8)

    axm.plot(df.index, df["MACD"], label="MACD", linewidth=1.0)
    axm.plot(df.index, df["MACD_SIGNAL"], label="Signal", linewidth=1.0)
    axm.bar(df.index, df["MACD_HIST"], label="Hist", alpha=.5)
    axm.axhline(0, linewidth=.8)
    axm.grid(alpha=.22)
    axm.legend(fontsize=8)

    axo.plot(df.index, df["OBV"], label="OBV", linewidth=1.0)
    axo.plot(df.index, df["OBV_EMA10"], label="OBV EMA10", linewidth=1.0)
    axo.grid(alpha=.22)
    axo.legend(fontsize=8)

    for ax in [axp, axr, axm, axo]:
        ax.tick_params(axis="x", labelrotation=20, labelsize=8)
        ax.tick_params(axis="y", labelsize=8)

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


# ============================================================
# TELEGRAM
# ============================================================

def tg_url(token, method):
    return f"https://api.telegram.org/bot{token}/{method}"


def telegram_send_message(token, chat_id, text):
    import requests

    url = f"https://api.telegram.org/bot{str(token).strip()}/sendMessage"

    payload = {
        "chat_id": str(chat_id).strip(),
        "text": str(text)[:3900]
    }

    r = requests.post(url, data=payload, timeout=30)

    print("TELEGRAM STATUS:", r.status_code)
    print("TELEGRAM RESPONSE:", r.text)

    r.raise_for_status()
    return r.text

    try:
        with urllib.request.urlopen(tg_url(str(token).strip(), "sendMessage"), data=data, timeout=30) as resp:
            return resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        print("TELEGRAM HTTP ERROR:", e.code)
        print("TELEGRAM ERROR BODY:", e.read().decode("utf-8", errors="ignore"))
        raise


def telegram_send_photo(token, chat_id, photo_path, caption):
    boundary = "----GokhanBistRadarBoundary"
    body = []

    def field(name, value):
        body.append(f"--{boundary}\r\n".encode())
        body.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.append(str(value).encode("utf-8"))
        body.append(b"\r\n")

    def filefield(name, filename, content):
        body.append(f"--{boundary}\r\n".encode())
        body.append(f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode())
        body.append(b"Content-Type: image/png\r\n\r\n")
        body.append(content)
        body.append(b"\r\n")

    field("chat_id", chat_id)
    field("caption", caption[:1000])
    field("parse_mode", "HTML")
    filefield("photo", photo_path.name, photo_path.read_bytes())
    body.append(f"--{boundary}--\r\n".encode())

    payload = b"".join(body)
    req = urllib.request.Request(tg_url(token, "sendPhoto"), data=payload)
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    req.add_header("Content-Length", str(len(payload)))

    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8")


def caption(r, tf):
    risk = r["risk_flags"] or "Belirgin risk bayrağı yok"

    return (
        f"<b>{r['symbol']}</b> | {tf} | Skor: <b>{r['score']}</b> | {r.get('quality_grade','')} | {r['status']}\n"
        f"Kurulum: {r['setup']}\n"
        f"Skor 15m/1s/4s/1g: {r['score_15m']} / {r['score_1h']} / {r['score_4h']} / {r['score_1d']}\n"
        f"RSI 15m/1s/4s/1g: {r['rsi_15m']} / {r['rsi_1h']} / {r['rsi_4h']} / {r['rsi_1d']}\n"
        f"Para girişi 15m/1s/4s/1g: {r['money_flow_15m']} / {r['money_flow_1h']} / {r['money_flow_4h']} / {r['money_flow_1d']}\n"
        f"Kırılım: {r['breakout_level']} | Stop: {r['breakout_stop']} | H1/H2: {r['breakout_target_1']} / {r['breakout_target_2']}\n"
        f"Fib 0.618: {r['fib_0618']} | Fib 1.618: {r['fib_1618']} | {r['fib_position']}\n"
        f"R/R: {r['risk_reward']} | RS20/RS60: {r.get('rs_xu100_20')} / {r.get('rs_xu100_60')}\n"
        f"Uyumsuzluk RSI 15m/1s: {r.get('div_15m')} / {r.get('div_1h')} | OBV 15m/1s: {r.get('div_obv_15m')} / {r.get('div_obv_1h')}\n"
        f"Takas: {r['takas_score']} | {r['takas_note']}\n"
        f"Risk: {risk}"
    )


# ============================================================
# MAIN
# ============================================================
def load_radar_memory(days=10):
    rows = []
    if not MEMORY_FILE.exists():
        return rows

    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception:
        return []

    return rows[-1000:]


def save_radar_memory(started, radar_name, top):
    old_rows = load_radar_memory()
    print("MEMORY WRITTEN:", MEMORY_FILE.exists(), MEMORY_FILE.resolve())
    new_rows = []
    for r in top:
        new_rows.append({
            "date": started,
            "radar": radar_name,
            "symbol": str(r.get("symbol", "")),
            "score": str(r.get("score", "")),
            "para15m": str(r.get("para15m", r.get("money_15m", ""))),
        })

    rows = old_rows + new_rows

    with open(MEMORY_FILE, "w", encoding="utf-8", newline="") as f:
        fieldnames = ["date", "radar", "symbol", "score", "para15m"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows[-1500:])

def save_radar_signals(started, radar_name, top):
    exists = SIGNALS_FILE.exists()

    with open(SIGNALS_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "date",
                "radar",
                "symbol",
                "score",
                "para15m"
            ]
        )

        if not exists:
            writer.writeheader()

        for r in top:
            writer.writerow({
                "date": started,
                "radar": radar_name,
                "symbol": str(r.get("symbol", "")),
                "score": str(r.get("score", "")),
                "para15m": str(r.get("para15m", ""))
            })

print("MEMORY FILE EXISTS:", os.path.exists("radar_memory.csv"))
def radar_memory_counts():
    rows = load_radar_memory()
    print("MEMORY ROWS:", len(rows))
    symbols = [r.get("symbol", "") for r in rows if r.get("symbol")]
    return Counter(symbols)


def format_memory_leaders(limit=5):
    rows = load_radar_memory()

    v9 = Counter()
    v13 = Counter()

    for r in rows:
        sym = r.get("symbol", "")
        radar = r.get("radar", "")

        if radar == "V9":
            v9[sym] += 1
        elif radar == "V13":
            v13[sym] += 1

    text = "\n🧠 <b>V9 Hafızası</b>\n"
    for sym, cnt in v9.most_common(limit):
        text += f"• {sym}: {cnt} kez\n"

    text += "\n🧠 <b>V13 Hafızası</b>\n"
    for sym, cnt in v13.most_common(limit):
        text += f"• {sym}: {cnt} kez\n"

    return text

def get_memory_count(symbol, radar_type=None):
    rows = load_radar_memory()
    count = 0

    for r in rows:
        if r.get("symbol") != symbol:
            continue
        if radar_type and r.get("radar") != radar_type:
            continue
        count += 1

    return count


def format_radar_favorites(current_symbols, limit=8):
    favorites = []

    for sym in current_symbols:
        v9_count = get_memory_count(sym, "V9")
        v13_count = get_memory_count(sym, "V13")

        trust = 0
        trust += min(v9_count * 3, 45)
        trust += min(v13_count * 5, 45)

        if v9_count > 0 and v13_count > 0:
            trust += 10

        trust = min(trust, 100)

        if trust >= 70:
            label = "🟢 ÇOK GÜÇLÜ"
        elif trust >= 40:
            label = "🟡 İZLE"
        else:
            label = "🔴 ERKEN ADAY"

        favorites.append((sym, v9_count, v13_count, trust, label))

    favorites = sorted(favorites, key=lambda x: x[3], reverse=True)

    text = "\n⭐ <b>RADAR FAVORİLERİ</b>\n"

    if not favorites:
        return text + "• Henüz veri yok.\n"

    for sym, v9c, v13c, trust, label in favorites[:limit]:
        text += (
            f"• {label} | {sym} → "
            f"V9:{v9c} | V13:{v13c} | Güven:{trust}/100\n"
        )

    return text

def main():
    cfg = load_config()

    token = os.getenv("TELEGRAM_BOT_TOKEN") or cfg.get("telegram_bot_token")
    chat_id = os.getenv("TELEGRAM_CHAT_ID") or cfg.get("telegram_chat_id")

    if not token or "BURAYA" in token or not chat_id or "BURAYA" in str(chat_id):
        print("Telegram token/chat_id ayarlanmamış.")
        return

    started = dt.datetime.now(ZoneInfo("Europe/Istanbul")).strftime("%d.%m.%Y %H:%M")
    symbols = load_symbols(cfg["symbols_file"])
    takas_map = load_takas()
    errors = []

    idx_raw = download(cfg["index_symbol"], cfg["period_daily"], "1d")
    idx = add_ind(idx_raw) if idx_raw is not None and len(idx_raw) >= 180 else None
    mkt_bonus, mkt_state = market_bonus(idx)

    results = []
    fallback = []

    for i, s in enumerate(symbols, start=1):
        print(f"[{i}/{len(symbols)}] {s}")
        try:
            r = analyze_symbol(s, cfg, mkt_bonus, takas_map, idx)
            if r is None:
                print(f"DEBUG NONE: {s}")
            else:
                print(f"DEBUG OK: {s} score={r.get('score')}")
            if r:
                results.append(r)
        except Exception as e:
            errors.append({
                "symbol": s,
                "error": str(e),
                "trace": traceback.format_exc()
            })
        time.sleep(cfg.get("sleep_between_symbols_sec", 0.03))

    results = sorted(results, key=lambda x: x["score"], reverse=True)
    def quality_filter(r):
        """
        V11 kalite filtresi:
        Sahte kırılımları elemek için negatif uyumsuzluk + RS XU100 + R/R birlikte değerlendirilir.
        """
        score = r.get("score", 0)

        money15 = r.get("money_flow_15m") or 0
        money1h = r.get("money_flow_1h") or 0
        money4h = r.get("money_flow_4h") or 0
        best_money = max(money15, money1h, money4h)

        breakout_ok = bool(r.get("near_breakout")) or bool(r.get("is_breakout"))

        rr = r.get("risk_reward")
        rr_value = rr if rr is not None else -999

        positive_div_ok = (
            r.get("div_15m") == "POZITIF"
            or r.get("div_1h") == "POZITIF"
            or r.get("div_4h") == "POZITIF"
        )

        fib_ok = r.get("fib_position") in [
            "0.618-1.000 arası / sağlıklı trend",
            "1.000-1.618 arası / hedef bölgesi"
        ]

        rs20 = r.get("rs_xu100_20")
        rs60 = r.get("rs_xu100_60")

        rs_not_weak = (
            (rs20 is None or rs20 >= -3)
            and (rs60 is None or rs60 >= -6)
        )

        rs_strong = (
            (rs20 is not None and rs20 >= 3)
            or (rs60 is not None and rs60 >= 5)
        )

        neg_rsi = (
            r.get("div_15m") == "NEGATIF"
            or r.get("div_1h") == "NEGATIF"
            or r.get("div_4h") == "NEGATIF"
        )

        neg_obv = (
            r.get("div_obv_15m") == "NEGATIF"
            or r.get("div_obv_1h") == "NEGATIF"
        )

        risk_text = (r.get("risk_flags") or "").lower()
        severe_risk = any(x in risk_text for x in [
            "likidite zayıf",
            "rsi sıcak",
            "zaten gitmiş olabilir",
            "üst fitil",
            "fib uzamış",
            "r/r zayıf"
        ])

        a_quality = (
            score >= 90
            and best_money >= 60
            and breakout_ok
            and rr_value >= 0.80
            and (positive_div_ok or fib_ok)
            and rs_not_weak
            and not neg_rsi
            and not neg_obv
            and not severe_risk
        )

        if a_quality:
            r["quality_grade"] = "A-KALİTE"
            return True

        b_watch = (
            score >= 88
            and best_money >= 55
            and breakout_ok
            and rr_value >= 0.50
            and fib_ok
            and rs_not_weak
            and not neg_rsi
            and not neg_obv
            and not severe_risk
        )

        if b_watch:
            r["quality_grade"] = "B-İZLEME"
            return True

        c_watch = (
            score >= 85
            and best_money >= 55
            and breakout_ok
            and rr_value >= 0.25
            and fib_ok
            and rs_strong
            and not neg_rsi
            and not neg_obv
            and not severe_risk
        )

        if c_watch:
            r["quality_grade"] = "C-SADECE İZLE"
            return True

        r["quality_grade"] = "ELENDİ"
        return False

    # V9 ERKEN RADAR: geniş momentum / para akışı listesi
    v9_top = sorted(
        results,
        key=lambda r: (
            r.get("score", 0),
            r.get("money_flow_15m") or r.get("para15m") or 0
        ),
        reverse=True
    )[:10]
    
    selected = [r for r in results if quality_filter(r)]

    # Hiç aday çıkmazsa, sadece RS güçlü ve ağır negatif uyumsuzluğu olmayan en iyi 3 izleme adayı.
    if not selected:
        fallback = []
        for r in results:
            rr = r.get("risk_reward")
            rr_value = rr if rr is not None else -999
            best_money = max(
                r.get("money_flow_15m") or 0,
                r.get("money_flow_1h") or 0,
                r.get("money_flow_4h") or 0
            )
            fib_ok = r.get("fib_position") in [
                "0.618-1.000 arası / sağlıklı trend",
                "1.000-1.618 arası / hedef bölgesi"
            ]
            breakout_ok = bool(r.get("near_breakout")) or bool(r.get("is_breakout"))
            neg_rsi = r.get("div_15m") == "NEGATIF" or r.get("div_1h") == "NEGATIF"
            neg_obv = r.get("div_obv_15m") == "NEGATIF" or r.get("div_obv_1h") == "NEGATIF"
            rs20 = r.get("rs_xu100_20")
            rs60 = r.get("rs_xu100_60")
            rs_strong = (rs20 is not None and rs20 >= 3) or (rs60 is not None and rs60 >= 5)

            if (
                r.get("score", 0) >= 85
                and best_money >= 55
                and breakout_ok
                and rr_value >= 0.25
                and fib_ok
                and rs_strong
                and not neg_rsi
                and not neg_obv
            ):
                r["quality_grade"] = "C-SADECE İZLE"
                fallback.append(r)

        selected = fallback[:3] if fallback else results[:3]
    top = selected[:cfg["top_n"]]

    clean = [{k: v for k, v in r.items() if k != "_frames"} for r in results]
    pd.DataFrame(clean).to_csv(OUT / "radar_results_v11.csv", index=False, encoding="utf-8-sig")

    pd.DataFrame([{k: v for k, v in r.items() if k != "_frames"} for r in top]).to_csv(
        OUT / "telegram_candidates_v11.csv",
        index=False,
        encoding="utf-8-sig"
    )

    if errors:
        pd.DataFrame(errors).to_csv(OUT / "errors_v11.csv", index=False, encoding="utf-8-sig")

    summary = (
        f"📡 <b>GÖKHAN BIST RADAR PRO</b>\n"
        f"Tarih: {started}\n"
        f"Piyasa: <b>{mkt_state}</b>\n"
        f"Taranan: {len(symbols)} | Aday havuzu: {len(results)} | V13 aday: {len(top)}\n\n"
    )

    summary += "🟦 <b>V9 ERKEN RADAR</b>\n"
    for r in v9_top[:10]:
        summary += (
            f"• {r['symbol']} skor {r.get('score')} | "
            f"para15m {r.get('money_flow_15m') or r.get('para15m') or 0} | "
            f"{','.join(r.get('_frames', {}).keys())} | "
            f"{r.get('reasons','')}\n"
        )

    summary += "\n🟩 <b>V13 KALİTE RADAR</b>\n"
    for r in top[:10]:
        summary += (
            f"• {r['symbol']} skor {r.get('score')} | "
            f"{r.get('quality_grade','')} | "
            f"para15m {r.get('money_flow_15m') or r.get('para15m') or 0} | "
            f"RS20 {r.get('rs_xu100_20')} | "
            f"kırılım {r.get('breakout_level')} | "
            f"fib1.618 {r.get('fib_1618')} | "
            f"R/R {r.get('risk_reward')} | "
            f"{','.join(r.get('_frames', {}).keys())} | "
            f"{r.get('reasons','')}\n"
        )

    v9_symbols = {r.get("symbol") for r in v9_top}
    v13_symbols = {r.get("symbol") for r in top}
    common_symbols = list(v9_symbols & v13_symbols)

    strong = []

    rows = load_radar_memory()

    for sym in common_symbols:

        v9_count = sum(
            1 for r in rows
            if r.get("symbol") == sym and r.get("radar") == "V9"
        )

        v13_count = sum(
            1 for r in rows
            if r.get("symbol") == sym and r.get("radar") == "V13"
        )

        if v9_count >= 2 and v13_count >= 2:
            strong.append(sym)
            
    summary += "\n🔥 <b>ORTAK RADAR</b>\n"
    if common_symbols:
        for sym in common_symbols[:10]:
            summary += f"• {sym} → V9 + V13 kesişimi\n"
    else:
        summary += "• Kesişim yok.\n"
        
    summary += "\n🔥 <b>GÜÇLÜ KESİŞİM</b>\n"

    if strong:
        for sym in strong:
            summary += f"• {sym}\n"
    else:
        summary += "• Henüz yok.\n"
        
    save_radar_memory(started, "V9", v9_top)
    save_radar_memory(started, "V13", top)

    save_radar_signals(started, "V9", v9_top)
    save_radar_signals(started, "V13", top)

    all_current_symbols = list(
        {r.get("symbol") for r in v9_top} |
        {r.get("symbol") for r in top}
    )

    summary += format_radar_favorites(all_current_symbols)
    summary += format_memory_leaders()

    telegram_send_message(token, chat_id, summary)


    # Grafik gönderimi kapatıldı
# for r in top[:cfg["send_chart_top_n"]]:
#     for tf in ["15M", "1H", "4H", "1D"]:
#         if tf in r.get("_frames", {}):
#             p = plot_timeframe_chart(r, tf)
#             telegram_send_photo(token, chat_id, p)

    print("Bitti. Telegram mesajları gönderildi.")
    print("CSV:", OUT / "telegram_candidates_v11.csv")


if __name__ == "__main__":
    main()
