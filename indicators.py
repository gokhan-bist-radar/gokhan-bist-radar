import pandas as pd
import numpy as np


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Kolon isimlerini standartlaştır
    df.columns = [str(c).lower() for c in df.columns]

    required = ["open", "high", "low", "close", "volume"]
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Eksik kolon: {col}")

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    # EMA
    for period in [8, 21, 50, 100, 200]:
        df[f"ema{period}"] = close.ewm(span=period, adjust=False).mean()

    # RSI 14
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()

    rs = avg_gain / avg_loss
    df["rsi"] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    # OBV
    direction = np.sign(close.diff()).fillna(0)
    df["obv"] = (direction * volume).cumsum()

    # Bollinger
    df["bb_mid"] = close.rolling(20).mean()
    df["bb_std"] = close.rolling(20).std()
    df["bb_upper"] = df["bb_mid"] + 2 * df["bb_std"]
    df["bb_lower"] = df["bb_mid"] - 2 * df["bb_std"]

    # ATR
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14).mean()

    # ADX
    plus_dm = high.diff()
    minus_dm = low.diff() * -1

    plus_dm = np.where((plus_dm > minus_dm) & (plus_dm > 0), plus_dm, 0)
    minus_dm = np.where((minus_dm > plus_dm) & (minus_dm > 0), minus_dm, 0)

    atr = df["atr"]
    df["plus_di"] = 100 * pd.Series(plus_dm, index=df.index).rolling(14).sum() / atr
    df["minus_di"] = 100 * pd.Series(minus_dm, index=df.index).rolling(14).sum() / atr

    dx = (abs(df["plus_di"] - df["minus_di"]) / (df["plus_di"] + df["minus_di"])) * 100
    df["adx"] = dx.rolling(14).mean()

    # Supertrend basit versiyon
    multiplier = 3
    hl2 = (high + low) / 2
    upperband = hl2 + multiplier * df["atr"]
    lowerband = hl2 - multiplier * df["atr"]

    df["supertrend"] = np.nan
    df["supertrend_direction"] = ""

    trend = True
    for i in range(1, len(df)):
        if close.iloc[i] > upperband.iloc[i - 1]:
            trend = True
        elif close.iloc[i] < lowerband.iloc[i - 1]:
            trend = False

        df.iloc[i, df.columns.get_loc("supertrend")] = lowerband.iloc[i] if trend else upperband.iloc[i]
        df.iloc[i, df.columns.get_loc("supertrend_direction")] = "AL" if trend else "SAT"

    # Hacim ortalaması ve göreli hacim
    df["volume_ma20"] = volume.rolling(20).mean()
    df["relative_volume"] = volume / df["volume_ma20"]

    return df