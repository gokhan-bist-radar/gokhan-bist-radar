import os
import mplfinance as mpf
import matplotlib.pyplot as plt

from data_provider import get_data
from indicators import add_indicators


OUTPUT_DIR = "charts"

os.makedirs(OUTPUT_DIR, exist_ok=True)


TIMEFRAMES = {
    "15m": "15dk",
    "1h": "1saat",
    "4h": "4saat",
    "1d": "gunluk",
    "1mo": "aylik",
}


def create_chart(symbol: str, timeframe: str):

    df = get_data(symbol, timeframe)
    df = add_indicators(df)

    apds = [
        mpf.make_addplot(df["ema8"], color="white"),
        mpf.make_addplot(df["ema21"], color="orange"),
        mpf.make_addplot(df["ema50"], color="dodgerblue"),
        mpf.make_addplot(df["ema100"], color="lime"),
        mpf.make_addplot(df["ema200"], color="magenta"),

        mpf.make_addplot(df["rsi"], panel=1, color="violet", ylabel="RSI"),
        mpf.make_addplot(df["macd"], panel=2, color="cyan", ylabel="MACD"),
        mpf.make_addplot(df["macd_signal"], panel=2, color="orange"),
        mpf.make_addplot(df["obv"], panel=3, color="white", ylabel="OBV"),
    ]

    filename = f"{symbol.upper().replace('#', '')}_{TIMEFRAMES[timeframe]}.jpg"
    filepath = os.path.join(OUTPUT_DIR, filename)

    style = mpf.make_mpf_style(
        base_mpf_style="nightclouds",
        facecolor="#0b0f19",
        edgecolor="#0b0f19",
        figcolor="#0b0f19",
        gridcolor="#1f2937",
        gridstyle="--"
    )

    fig, axes = mpf.plot(
        df,
        type="candle",
        style=style,
        volume=True,
        addplot=apds,
        panel_ratios=(6, 2, 2, 2),
        figsize=(16, 10),
        title=f"{symbol.upper()} - {timeframe}",
        tight_layout=True,
        returnfig=True
    )

    fig.savefig(filepath, dpi=180)

    plt.close(fig)

    return filepath


def create_all_charts(symbol: str):

    results = []

    for tf in TIMEFRAMES.keys():

        try:
            path = create_chart(symbol, tf)
            results.append(path)

        except Exception as e:
            print(f"HATA {tf}: {e}")

    return results


if __name__ == "__main__":

    hisse = input("Hisse kodu gir (#BRYAT): ")

    files = create_all_charts(hisse)

    print("\nOLUŞTURULAN GRAFİKLER:")

    for f in files:
        print(f)