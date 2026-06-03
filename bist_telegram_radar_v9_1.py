
import datetime as dt
import json
import os
import time
import traceback
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
from chart_engine import create_all_charts

OUT = Path("outputs")
CHARTS = OUT / "charts"
OUT.mkdir(exist_ok=True)
CHARTS.mkdir(exist_ok=True)


def load_config():
    return json.loads(Path("config.json").read_text(encoding="utf-8"))


def load_symbols(path):
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        x = line.strip().upper()
        if x and not x.startswith("#"):
            out.append(x[:-3] if x.endswith(".IS") else x)
    return sorted(set(out))


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
    df = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=False, threads=False)
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df.dropna().copy()
    for c in ["Open", "High", "Low", "Close", "Volume"]:
        if c not in df.columns:
            return None
    return df


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


def market_bonus(index_df):
    if index_df is None or len(index_df) < 220:
        return 0, "Bilinmiyor"
    r = index_df.iloc[-1]
    score = 0
    if r["Close"] > r["EMA21"]: score += 1
    if r["EMA21"] > r["EMA50"]: score += 1
    if r["Close"] > r["EMA200"]: score += 1
    if r["RSI14"] > 45: score += 1
    if r["RET_20"] > 0: score += 1
    if score >= 4: return 8, "Pozitif"
    if score == 3: return 3, "Nötr+"
    if score == 2: return -5, "Yatay/Riskli"
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
            score += pts; notes.append(name)
        elif val < -2:
            score -= pts; notes.append(name + " negatif")
    return max(-20, min(20, score)), " | ".join(notes) if notes else "Takas nötr"


def money_flow_score(df, volume_mult=1.8):
    r = df.iloc[-1]
    prev = df.iloc[-2]
    score = 0
    notes = []
    if r["OBV"] > r["OBV_EMA10"]:
        score += 20; notes.append("OBV pozitif")
    if len(df) > 12 and df["OBV"].iloc[-1] > df["OBV"].iloc[-10]:
        score += 15; notes.append("OBV trend yukarı")
    if r["CMF20"] > 0.08:
        score += 20; notes.append("CMF para girişi")
    elif r["CMF20"] > 0:
        score += 10; notes.append("CMF pozitif")
    if r["MFI14"] > 55 and r["MFI14"] < 80:
        score += 15; notes.append("MFI güçlü")
    if r["VOL_AVG20"] and r["Volume"] > r["VOL_AVG20"] * volume_mult and r["Close"] > r["Open"]:
        score += 20; notes.append("Yeşil hacim patlaması")
    if r["MACD_HIST"] > prev["MACD_HIST"] and r["MACD_HIST"] > 0:
        score += 10; notes.append("MACD para momentumu")
    return max(0, min(100, int(score))), " | ".join(notes)


def tf_score(df, min_value_tl, bonus=0, volume_mult=1.8):
    if df is None or len(df) < 70:
        return 0, {}, "Veri yok"
    r = df.iloc[-1]
    prev = df.iloc[-2]
    score = 0
    notes = []
    flags = []

    if r["EMA8"] > r["EMA21"]:
        score += 12; notes.append("EMA8>21")
    if r["EMA21"] >= r["EMA50"] * 0.995:
        score += 10; notes.append("EMA21/50 yakın")
    if r["Close"] > r["EMA8"]:
        score += 8; notes.append("Fiyat EMA8 üstü")
    if r["MACD_HIST"] > prev["MACD_HIST"]:
        score += 13; notes.append("MACD hist artıyor")
    if r["MACD"] > r["MACD_SIGNAL"]:
        score += 10; notes.append("MACD pozitif")
    if r["OBV"] > r["OBV_EMA10"]:
        score += 10; notes.append("OBV pozitif")
    if r["VOL_AVG20"] and r["Volume"] > r["VOL_AVG20"] * 1.3:
        score += 10; notes.append("Hacim kıpırdanıyor")
    if 48 <= r["RSI14"] <= 66:
        score += 10; notes.append("RSI uygun")
    if r["Close"] >= df["RES10"].iloc[-2] * 0.985:
        score += 9; notes.append("Dirence yakın")
    if r["RANGE10_PCT"] <= 6.8:
        score += 8; notes.append("Sıkışma")

    div = rsi_divergence(df)
    if div == "POZITIF":
        score += 10; notes.append("RSI pozitif uyumsuzluk")
    elif div == "NEGATIF":
        score -= 12; flags.append("RSI negatif uyumsuzluk")

    if r["VALUE_AVG20_TL"] < min_value_tl:
        score -= 15; flags.append("Likidite zayıf")
    if r["RSI14"] > 74:
        score -= 12; flags.append("RSI sıcak")
    if r["RET_1"] > 8.5:
        score -= 15; flags.append("Zaten gitmiş olabilir")
    if r["UPPER_WICK_PCT"] > 5:
        score -= 8; flags.append("Üst fitil")

    mf_score, mf_note = money_flow_score(df, volume_mult)
    if mf_score >= 65:
        score += 12; notes.append("Güçlü para girişi")
    elif mf_score >= 45:
        score += 6; notes.append("Para girişi orta")

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
        "money_flow_score": mf_score,
        "money_flow_note": mf_note,
        "notes": " | ".join(notes),
        "flags": " | ".join(flags),
        "support": round(float(r["SUP20"]), 2),
        "resistance": round(float(r["RES20"]), 2),
        "stop": round(float(r["Close"] - 1.5 * r["ATR14"]), 2) if not pd.isna(r["ATR14"]) else None,
        "target": round(float(r["Close"] + 2.0 * r["ATR14"]), 2) if not pd.isna(r["ATR14"]) else None,
    }
    return max(0, min(100, int(score))), state, " | ".join(notes + flags)


def empty_state():
    return {
        "close": None, "rsi": None, "mfi": None, "cmf": None, "macd_hist": None,
        "obv_ok": None, "volume_ratio": None, "divergence": "YOK",
        "money_flow_score": 0, "money_flow_note": "Veri yok",
        "notes": "", "flags": "Veri yok", "support": None, "resistance": None,
        "stop": None, "target": None
    }


def analyze_symbol(sym, cfg, mkt_bonus, takas_map):
    y = sym + ".IS"

    d1_raw = download(y, cfg["period_daily"], "1d")
    if d1_raw is None or len(d1_raw) < 120:
        return None
    d1 = add_ind(d1_raw)

    # 15m veri her hissede gelmeyebilir. Gelmezse hisseyi eleme; 1h veriye düş.
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

    # 15m kaynak yoksa doğrudan 1h veriyi dene
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

    # Dinamik ağırlık: hangi veri varsa ona göre puanla.
    if m15 is not None and h1 is not None and h4 is not None:
        total = int(round(s15 * 0.32 + s1h * 0.28 + s4h * 0.25 + s1d * 0.15 + ts * 0.30))
    elif h1 is not None and h4 is not None:
        total = int(round(s1h * 0.45 + s4h * 0.35 + s1d * 0.20 + ts * 0.30))
    elif h1 is not None:
        total = int(round(s1h * 0.65 + s1d * 0.35 + ts * 0.30))
    else:
        total = int(round(s1d + ts * 0.30))

    status = "PATLAMA ADAYI" if total >= cfg["early_score_threshold"] else "YAKIN İZLE" if total >= cfg["early_score_threshold"] - 10 else "BEKLE"

    setup = []
    if s15 >= 70: setup.append("15dk tetik")
    if s1h >= 70: setup.append("1s onay")
    if s4h >= 70: setup.append("4s kurulum")
    if s1d >= 65: setup.append("günlük destek")
    if st15["money_flow_score"] >= cfg["strong_money_flow_threshold"]:
        setup.append("15dk güçlü para girişi")
    elif st1h["money_flow_score"] >= cfg["strong_money_flow_threshold"]:
        setup.append("1s güçlü para girişi")
    if st15["divergence"] == "POZITIF" or st1h["divergence"] == "POZITIF":
        setup.append("RSI pozitif uyumsuzluk")
    if ts > 0:
        setup.append("takas pozitif")
    setup.append("veri:" + ",".join(available_tfs))

    frames = {"1D": d1}
    if h4 is not None: frames["4H"] = h4
    if h1 is not None: frames["1H"] = h1
    if m15 is not None: frames["15M"] = m15

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
        "support": st1d["support"],
        "resistance": st1d["resistance"],
        "stop": st1d["stop"],
        "target": st1d["target"],
        "risk_flags": " | ".join([x for x in [st15.get("flags"), st1h.get("flags"), st4h.get("flags"), st1d.get("flags")] if x and x != "Veri yok"]),
        "available_tfs": ",".join(available_tfs),
        "_frames": frames
    }


def swing_fib_levels(df):
    d = df.tail(120)
    lows = pivots(d["Low"], 3, "low")
    highs = pivots(d["High"], 3, "high")
    if not lows or not highs:
        return None
    # find last swing low before last swing high for uptrend extension
    high_i = highs[-1]
    low_candidates = [i for i in lows if i < high_i]
    if not low_candidates:
        return None
    low_i = low_candidates[-1]
    low = float(d["Low"].iloc[low_i])
    high = float(d["High"].iloc[high_i])
    if high <= low:
        return None
    diff = high - low
    return {
        "low": low,
        "high": high,
        "1.272": high + diff * 0.272,
        "1.618": high + diff * 0.618,
        "2.000": high + diff * 1.000
    }


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

    if tf == "15M" and result.get("money_flow_15m", 0) >= cfg["strong_money_flow_threshold"]:
        fib = swing_fib_levels(df)
        if fib:
            axp.axhline(fib["high"], linestyle="--", linewidth=.9, label="Swing High")
            axp.axhline(fib["1.272"], linestyle=":", linewidth=.9, label="Fib 1.272")
            axp.axhline(fib["1.618"], linestyle=":", linewidth=.9, label="Fib 1.618")
            axp.axhline(fib["2.000"], linestyle=":", linewidth=.9, label="Fib 2.000")

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
        ax.tick_params(axis='x', labelrotation=20, labelsize=8)
        ax.tick_params(axis='y', labelsize=8)

    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def tg_url(token, method):
    return f"https://api.telegram.org/bot{token}/{method}"


def telegram_send_message(token, chat_id, text):
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
    with urllib.request.urlopen(tg_url(token, "sendMessage"), data=data, timeout=30) as resp:
        return resp.read().decode("utf-8")


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
        f"<b>{r['symbol']}</b> | {tf} | Skor: <b>{r['score']}</b> | {r['status']}\n"
        f"Kurulum: {r['setup']}\n"
        f"Skor 15m/1s/4s/1g: {r['score_15m']} / {r['score_1h']} / {r['score_4h']} / {r['score_1d']}\n"
        f"RSI 15m/1s/4s/1g: {r['rsi_15m']} / {r['rsi_1h']} / {r['rsi_4h']} / {r['rsi_1d']}\n"
        f"Para girişi 15m/1s/4s/1g: {r['money_flow_15m']} / {r['money_flow_1h']} / {r['money_flow_4h']} / {r['money_flow_1d']}\n"
        f"Takas: {r['takas_score']} | {r['takas_note']}\n"
        f"Fiyat: {r['close']} | Stop: {r['stop']} | Hedef: {r['target']}\n"
        f"Risk: {risk}"
    )


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
    for i, s in enumerate(symbols, start=1):
        print(f"[{i}/{len(symbols)}] {s}")
        try:
            r = analyze_symbol(s, cfg, mkt_bonus, takas_map)
            if r:
                results.append(r)
        except Exception as e:
            errors.append({"symbol": s, "error": str(e), "trace": traceback.format_exc()})
        time.sleep(cfg.get("sleep_between_symbols_sec", 0.03))

    results = sorted(results, key=lambda x: x["score"], reverse=True)
    selected = [r for r in results if r["score"] >= cfg["early_score_threshold"]]
    top = selected[:cfg["top_n"]]

    clean = [{k: v for k, v in r.items() if k != "_frames"} for r in results]
    pd.DataFrame(clean).to_csv(OUT / "radar_results.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([{k: v for k, v in r.items() if k != "_frames"} for r in top]).to_csv(OUT / "telegram_candidates.csv", index=False, encoding="utf-8-sig")
    if errors:
        pd.DataFrame(errors).to_csv(OUT / "errors.csv", index=False, encoding="utf-8-sig")

    summary = (
        f"📡 <b>Gökhan BIST Radar V9.1</b>\n"
        f"Tarih: {started}\n"
        f"Piyasa: <b>{mkt_state}</b>\n"
        f"Taranan: {len(symbols)} | Veri gelen: {len(results)}\n"
        f"Erken patlama eşiği: {cfg['early_score_threshold']}\n"
        f"Aday sayısı: <b>{len(top)}</b>\n\n"
        f"İlk adaylar:\n"
    )
    for r in top[:10]:
        summary += f"• {r['symbol']} skor {r['score']} | para15m {r['money_flow_15m']} | {r.get('available_tfs','')} | {r['setup']}\n"

    telegram_send_message(token, chat_id, summary)

    for r in top[:cfg["send_chart_top_n"]]:
        for tf in ["15M", "1H", "4H", "1D"]:
            if tf in r.get("_frames", {}):
                p = plot_timeframe_chart(r, tf, cfg)
                telegram_send_photo(token, chat_id, p, caption(r, tf))

    print("Bitti. Telegram mesajları gönderildi.")
    print("CSV:", OUT / "telegram_candidates.csv")


if __name__ == "__main__":
    main()
