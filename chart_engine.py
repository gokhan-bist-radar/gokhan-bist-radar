import os
import matplotlib
matplotlib.use("Agg")

import mplfinance as mpf
import matplotlib.pyplot as plt

from data_provider import get_data
from indicators import add_indicators


OUTPUT_DIR = "charts"
os.makedirs(OUTPUT_DIR, exist_ok=True)


TIMEFRAMES = {
    "1mo": "aylik",
    "1d": "gunluk",
    "4h": "4saat",
    "1h": "1saat",
    "15m": "15dk",
}


def create_chart(symbol: str, timeframe: str) -> str:
    clean_symbol = symbol.upper().replace("#", "").strip()

    df = get_data(clean_symbol, timeframe)
    df = add_indicators(df)

    if len(df) > 220:
        plot_df = df.tail(220).copy()
    else:
        plot_df = df.copy()

    addplots = [
        mpf.make_addplot(plot_df["ema8"], color="white", width=0.7),
        mpf.make_addplot(plot_df["ema21"], color="orange", width=0.9),
        mpf.make_addplot(plot_df["ema50"], color="dodgerblue", width=0.9),
        mpf.make_addplot(plot_df["ema100"], color="lime", width=0.8),
        mpf.make_addplot(plot_df["ema200"], color="magenta", width=0.8),
        mpf.make_addplot(plot_df["bb_upper"], color="gray", width=0.5),
        mpf.make_addplot(plot_df["bb_lower"], color="gray", width=0.5),

        mpf.make_addplot(plot_df["rsi"], panel=2, color="violet", ylabel="RSI"),
        mpf.make_addplot(plot_df["macd"], panel=3, color="cyan", ylabel="MACD"),
        mpf.make_addplot(plot_df["macd_signal"], panel=3, color="orange"),
        mpf.make_addplot(plot_df["obv"], panel=4, color="white", ylabel="OBV"),
    ]

    style = mpf.make_mpf_style(
        base_mpf_style="nightclouds",
        facecolor="#0b0f19",
        figcolor="#0b0f19",
        edgecolor="#0b0f19",
        gridcolor="#1f2937",
        gridstyle="--",
    )

    filename = f"{clean_symbol}_{TIMEFRAMES[timeframe]}.jpg"
    filepath = os.path.join(OUTPUT_DIR, filename)

    title = f"{clean_symbol} - {TIMEFRAMES[timeframe].upper()}"

    fig, axes = mpf.plot(
        plot_df,
        type="candle",
        style=style,
        volume=True,
        addplot=addplots,
        panel_ratios=(6, 1.5, 1.5, 1.5, 1.5),
        figsize=(16, 11),
        title=title,
        tight_layout=True,
        returnfig=True,
        warn_too_much_data=10000,
    )

    fig.savefig(filepath, dpi=160, bbox_inches="tight")
    plt.close(fig)

    return filepath


def create_all_charts(symbol: str):
    files = []

    for timeframe in TIMEFRAMES:
        try:
            path = create_chart(symbol, timeframe)
            files.append(path)
        except Exception as e:
            print(f"{symbol} {timeframe} grafik hatası: {e}")

    return files