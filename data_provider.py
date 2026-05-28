import yfinance as yf
import pandas as pd


INTERVAL_MAP = {
    "15m": ("15m", "60d"),
    "1h": ("60m", "730d"),
    "4h": ("1d", "5y"),
    "1d": ("1d", "10y"),
    "1mo": ("1mo", "max"),
}


def get_data(symbol: str, timeframe: str = "1d") -> pd.DataFrame:

    symbol = symbol.upper().replace("#", "")

    if not symbol.endswith(".IS"):
        symbol = f"{symbol}.IS"

    interval, period = INTERVAL_MAP.get(timeframe, ("1d", "1y"))

    df = yf.download(
        tickers=symbol,
        interval=interval,
        period=period,
        auto_adjust=False,
        progress=False
    )

    if df.empty:
        raise ValueError(f"Veri alınamadı: {symbol}")

    df = df.rename(columns={
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Adj Close": "adj_close",
        "Volume": "volume"
    })

    df = df[["open", "high", "low", "close", "volume"]]

    df.dropna(inplace=True)

    return df