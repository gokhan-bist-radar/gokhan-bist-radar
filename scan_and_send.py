import os
import requests
import traceback
from chart_engine import create_all_charts

BOT_TOKEN = "BURAYA_BOT_TOKEN"
CHAT_ID = "BURAYA_CHAT_ID"

BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"

TAKIP_LISTESI = [
    "BRYAT",
    "MIATK",
    "GEDZA",
    "ODINE",
    "KORDS"
]


def send_message(text):
    requests.post(
        f"{BASE_URL}/sendMessage",
        data={"chat_id": CHAT_ID, "text": str(text)[:3900]},
        timeout=30
    )


def send_photo(path):
    with open(path, "rb") as photo:
        requests.post(
            f"{BASE_URL}/sendPhoto",
            data={"chat_id": CHAT_ID},
            files={"photo": photo},
            timeout=60
        )


def main():
    try:
        send_message("GOKHAN_BIST_RADAR_PRO otomatik tarama başladı.")

        for symbol in TAKIP_LISTESI:
            send_message(f"{symbol} grafik hazırlanıyor...")

            files = create_all_charts(symbol)

            if not files:
                send_message(f"{symbol} için grafik oluşturulamadı.")
                continue

            for file_path in files:
                send_photo(file_path)

            send_message(f"{symbol} grafik taraması tamamlandı.")

        send_message("Otomatik tarama tamamlandı.")

    except Exception:
        send_message(traceback.format_exc())


if __name__ == "__main__":
    main()