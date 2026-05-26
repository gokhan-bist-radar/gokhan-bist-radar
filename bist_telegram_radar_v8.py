
import datetime as dt
import json
import os
import time
import traceback
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt


OUT = Path("outputs")
CHARTS = OUT / "charts"
OUT.mkdir(exist_ok=True)
CHARTS.mkdir(exist_ok=True)


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


def load_config():
    return json.loads(Path("config.json").read_text(encoding="utf-8"))


def load_symbols(path):
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        x = line.strip().upper()
        if x and not x.startswith("#"):
            out.append(x[:-3] if x.endswith(".IS") else x)
    return sorted(set(out))


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


def resample_4h(df_1h):
    if df_1h is None or df_1h.empty:
        return None
    out = df_1h.resample("4h").agg({
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
    df["VOL_AVG20"] = df["Volume"].rolling(20).mean()
    df["VALUE_TL"] = df["Close"] * df["Volume"]
    df["VALUE_AVG20_TL"] = df["VALUE_TL"].rolling(20).mean()
    df["RES10"] = df["High"].rolling(10).max()
    df["RES20"] = df["High"].rolling(20).max()
    df["SUP20"] = df["Low"].rolling(20).min()
    df["RET_1"] = df["Close"].pct_change(1) * 100
    df["RET_20"] = df["Close"].pct_change(20) * 100
    df["RANGE10_PCT"] = ((df["High"].rolling(10).max() - df["Low"].rolling(10).min()) / df["Close"]) * 100
    df["UPPER_WICK_PCT"] = ((df["High"] - df[["Open", "Close"]].max(axis=1)) / df["Close"]) * 100
    return df


def pivots(series, order=3, kind="low"):
    vals = series.values
    out = []
    for i in range(order, len(vals) - order):
        window = vals[i-order:i+order+1]
        if kind == "low" and vals[i] == np.nanmin(window):
            out.append(i)
        elif kind == "high" and vals[i] == np.nanmax(window):
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
    if score >= 4:
        return 8, "Pozitif"
    if score == 3:
        return 3, "Nötr+"
    if score == 2:
        return -5, "Yatay/Riskli"
    return -15, "Negatif"


def tf_score(df, min_value_tl, bonus=0):
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

    score += bonus
    state = {
        "close": round(float(r["Close"]), 2),
        "rsi": round(float(r["RSI14"]), 2),
        "macd_hist": round(float(r["MACD_HIST"]), 4),
        "obv_ok": bool(r["OBV"] > r["OBV_EMA10"]),
        "volume_ratio": round(float(r["Volume"] / r["VOL_AVG20"]), 2) if r["VOL_AVG20"] else None,
        "divergence": div,
        "notes": " | ".join(notes),
        "flags": " | ".join(flags),
        "support": round(float(r["SUP20"]), 2),
        "resistance": round(float(r["RES20"]), 2),
        "stop": round(float(r["Close"] - 1.5 * r["ATR14"]), 2) if not pd.isna(r["ATR14"]) else None,
        "target": round(float(r["Close"] + 2.0 * r["ATR14"]), 2) if not pd.isna(r["ATR14"]) else None,
    }
    return max(0, min(100, int(score))), state, " | ".join(notes + flags)


def analyze_symbol(sym, cfg, mkt_bonus):
    y = sym + ".IS"
    d1_raw = download(y, cfg["period_daily"], "1d")
    h1_raw = download(y, cfg["period_hourly"], "1h")
    if d1_raw is None or h1_raw is None or len(d1_raw) < 220 or len(h1_raw) < 70:
        return None

    d1 = add_ind(d1_raw)
    h1 = add_ind(h1_raw)
    h4_raw = resample_4h(h1_raw)
    if h4_raw is None:
        return None
    h4 = add_ind(h4_raw)

    s1h, st1h, _ = tf_score(h1, cfg["min_avg_value_TL"], 0)
    s4h, st4h, _ = tf_score(h4, cfg["min_avg_value_TL"], 0)
    s1d, st1d, _ = tf_score(d1, cfg["min_avg_value_TL"], mkt_bonus)

    total = int(round(s1h * 0.45 + s4h * 0.35 + s1d * 0.20))
    status = "ERKEN FIRSAT" if total >= cfg["early_score_threshold"] else "YAKIN İZLE" if total >= cfg["early_score_threshold"] - 10 else "BEKLE"
    setup = []
    if s1h >= 70: setup.append("1s tetik")
    if s4h >= 70: setup.append("4s kurulum")
    if s1d >= 65: setup.append("günlük destek")
    if st1h.get("divergence") == "POZITIF" or st4h.get("divergence") == "POZITIF":
        setup.append("pozitif RSI uyumsuzluk")

    return {
        "symbol": y,
        "score": total,
        "status": status,
        "setup": " + ".join(setup) if setup else "erken/zayıf kurulum",
        "close": st1d["close"],
        "score_1h": s1h,
        "score_4h": s4h,
        "score_1d": s1d,
        "rsi_1h": st1h["rsi"],
        "rsi_4h": st4h["rsi"],
        "rsi_1d": st1d["rsi"],
        "div_1h": st1h["divergence"],
        "div_4h": st4h["divergence"],
        "div_1d": st1d["divergence"],
        "vol_1h": st1h["volume_ratio"],
        "vol_4h": st4h["volume_ratio"],
        "vol_1d": st1d["volume_ratio"],
        "support": st1d["support"],
        "resistance": st1d["resistance"],
        "stop": st1d["stop"],
        "target": st1d["target"],
        "risk_flags": " | ".join([x for x in [st1h.get("flags"), st4h.get("flags"), st1d.get("flags")] if x]),
        "_frames": {"1H": h1, "4H": h4, "1D": d1}
    }


def plot_symbol(result):
    sym = result["symbol"].replace(".IS", "")
    frames = result["_frames"]
    path = CHARTS / f"{sym}_1h_4h_1d.png"
    plt.style.use("dark_background")
    fig = plt.figure(figsize=(16, 12))
    fig.suptitle(f"{sym} | Skor {result['score']} | {result['status']} | {result['setup']}", fontsize=16)
    for col, tf in enumerate(["1H", "4H", "1D"], start=1):
        df = frames[tf].tail(120)
        axp = fig.add_subplot(4, 3, col)
        axr = fig.add_subplot(4, 3, 3 + col, sharex=axp)
        axm = fig.add_subplot(4, 3, 6 + col, sharex=axp)
        axo = fig.add_subplot(4, 3, 9 + col, sharex=axp)

        axp.plot(df.index, df["Close"], label="Fiyat", linewidth=1.2)
        axp.plot(df.index, df["EMA8"], label="EMA8", linewidth=.9)
        axp.plot(df.index, df["EMA21"], label="EMA21", linewidth=.9)
        axp.plot(df.index, df["EMA50"], label="EMA50", linewidth=.9)
        axp.set_title(tf)
        axp.grid(alpha=.22)
        axp.legend(fontsize=7)

        axr.plot(df.index, df["RSI14"], label="RSI14", linewidth=1.0)
        axr.axhline(70, linestyle="--", linewidth=.7)
        axr.axhline(50, linestyle="--", linewidth=.7)
        axr.axhline(30, linestyle="--", linewidth=.7)
        axr.grid(alpha=.22)
        axr.legend(fontsize=7)

        axm.plot(df.index, df["MACD"], label="MACD", linewidth=.9)
        axm.plot(df.index, df["MACD_SIGNAL"], label="Signal", linewidth=.9)
        axm.bar(df.index, df["MACD_HIST"], label="Hist", alpha=.5)
        axm.axhline(0, linewidth=.7)
        axm.grid(alpha=.22)
        axm.legend(fontsize=7)

        axo.plot(df.index, df["OBV"], label="OBV", linewidth=.9)
        axo.plot(df.index, df["OBV_EMA10"], label="OBV EMA10", linewidth=.9)
        axo.grid(alpha=.22)
        axo.legend(fontsize=7)

        for ax in [axp, axr, axm, axo]:
            ax.tick_params(axis='x', labelrotation=25, labelsize=7)
            ax.tick_params(axis='y', labelsize=7)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(path, dpi=140)
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


def caption(r):
    risk = r["risk_flags"] or "Belirgin risk bayrağı yok"
    return (
        f"<b>{r['symbol']}</b> | Skor: <b>{r['score']}</b> | {r['status']}\n"
        f"Kurulum: {r['setup']}\n"
        f"1s/4s/Günlük skor: {r['score_1h']} / {r['score_4h']} / {r['score_1d']}\n"
        f"RSI: {r['rsi_1h']} / {r['rsi_4h']} / {r['rsi_1d']}\n"
        f"Uyumsuzluk: {r['div_1h']} / {r['div_4h']} / {r['div_1d']}\n"
        f"Fiyat: {r['close']} | Stop: {r['stop']} | Hedef: {r['target']}\n"
        f"Risk: {risk}"
    )


def main():
    cfg = load_config()
    token = cfg.get("telegram_bot_token") or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = cfg.get("telegram_chat_id") or os.getenv("TELEGRAM_CHAT_ID")
    if not token or "BURAYA" in token or not chat_id or "BURAYA" in str(chat_id):
        print("Telegram token/chat_id ayarlanmamış. config.json dosyasını doldur.")
        return

    started = dt.datetime.now().strftime("%d.%m.%Y %H:%M")
    symbols = load_symbols(cfg["symbols_file"])
    errors = []

    idx_raw = download(cfg["index_symbol"], cfg["period_daily"], "1d")
    idx = add_ind(idx_raw) if idx_raw is not None and len(idx_raw) >= 220 else None
    mkt_bonus, mkt_state = market_bonus(idx)

    results = []
    for i, s in enumerate(symbols, start=1):
        print(f"[{i}/{len(symbols)}] {s}")
        try:
            r = analyze_symbol(s, cfg, mkt_bonus)
            if r:
                results.append(r)
        except Exception as e:
            errors.append({"symbol": s, "error": str(e), "trace": traceback.format_exc()})
        time.sleep(cfg.get("sleep_between_symbols_sec", 0.05))

    results = sorted(results, key=lambda x: x["score"], reverse=True)
    selected = [r for r in results if r["score"] >= cfg["early_score_threshold"]]
    top = selected[:cfg["top_n"]]

    clean = [{k: v for k, v in r.items() if k != "_frames"} for r in results]
    pd.DataFrame(clean).to_csv(OUT / "radar_results.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([{k: v for k, v in r.items() if k != "_frames"} for r in top]).to_csv(OUT / "telegram_candidates.csv", index=False, encoding="utf-8-sig")
    if errors:
        pd.DataFrame(errors).to_csv(OUT / "errors.csv", index=False, encoding="utf-8-sig")

    summary = (
        f"📡 <b>Gökhan BIST Radar V8</b>\n"
        f"Tarih: {started}\n"
        f"Piyasa: <b>{mkt_state}</b>\n"
        f"Taranan: {len(symbols)} | Veri gelen: {len(results)}\n"
        f"Erken fırsat eşiği: {cfg['early_score_threshold']}\n"
        f"Aday sayısı: <b>{len(top)}</b>\n\n"
        f"İlk adaylar:\n"
    )
    for r in top[:10]:
        summary += f"• {r['symbol']} skor {r['score']} | {r['setup']}\n"

    telegram_send_message(token, chat_id, summary)

    for r in top[:cfg["send_chart_top_n"]]:
        p = plot_symbol(r)
        telegram_send_photo(token, chat_id, p, caption(r))

    print("Bitti. Telegram mesajları gönderildi.")
    print("CSV:", OUT / "telegram_candidates.csv")


if __name__ == "__main__":
    main()
