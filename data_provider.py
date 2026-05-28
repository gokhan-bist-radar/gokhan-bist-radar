import yfinance as yf
import pandas as pd


INTERVAL_MAP = {
    "15m": ("15m", "60d"),
    "1h": ("60m", "730d"),
    "4h": ("60m", "730d"),
    "1d": ("1d", "10y"),
    "1mo": ("1mo", "max"),
}


def get_data(symbol: str, timeframe: str = "1d") -> pd.DataFrame:
    symbol = symbol.upper().replace("#", "").strip()

    if not symbol.endswith(".IS"):
        yf_symbol = f"{symbol}.IS"
    else:
        yf_symbol = symbol

    interval, period = INTERVAL_MAP.get(timeframe, ("1d", "1y"))

    df = yf.download(
        tickers=yf_symbol,
        interval=interval,
        period=period,
        auto_adjust=False,
        progress=False,
        threads=False,
    )

    if df.empty:
        raise ValueError(f"Veri alınamadı: {yf_symbol} / {timeframe}")

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.rename(columns={
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    })

    df = df[["open", "high", "low", "close", "volume"]].copy()
    df.dropna(inplace=True)

    if timeframe == "4h":
        df = df.resample("4h").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna()

    return df