import time
import requests
import os

from chart_engine import create_all_charts


BOT_TOKEN = "BURAYA_BOT_TOKEN"
CHAT_ID = "BURAYA_CHAT_ID"

BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


LAST_UPDATE_ID = None


def get_updates():

    global LAST_UPDATE_ID

    url = f"{BASE_URL}/getUpdates"

    params = {
        "timeout": 30
    }

    if LAST_UPDATE_ID:
        params["offset"] = LAST_UPDATE_ID + 1

    response = requests.get(url, params=params)

    return response.json()


def send_message(text):

    url = f"{BASE_URL}/sendMessage"

    data = {
        "chat_id": CHAT_ID,
        "text": text
    }

    requests.post(url, data=data)


def send_photo(photo_path):

    url = f"{BASE_URL}/sendPhoto"

    with open(photo_path, "rb") as photo:

        files = {
            "photo": photo
        }

        data = {
            "chat_id": CHAT_ID
        }

        requests.post(url, files=files, data=data)


def process_message(text):

    text = text.strip().upper()

    if not text.startswith("#"):
        return

    symbol = text.replace("#", "").strip()

    send_message(f"{symbol} grafik hazırlanıyor...")

    try:

        files = create_all_charts(symbol)

        for file_path in files:
            send_photo(file_path)

        send_message(f"{symbol} analiz tamamlandı.")

    except Exception as e:

        send_message(f"HATA: {e}")


def main():

    global LAST_UPDATE_ID

    send_message("GOKHAN_BIST_RADAR_PRO aktif.")

    while True:

        try:

            data = get_updates()

            if "result" in data:

                for item in data["result"]:

                    LAST_UPDATE_ID = item["update_id"]

                    if "message" in item:

                        msg = item["message"]

                        if "text" in msg:

                            text = msg["text"]

                            process_message(text)

        except Exception as e:

            print("HATA:", e)

        time.sleep(3)


if __name__ == "__main__":
    main()