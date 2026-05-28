import time
import requests
import traceback

from chart_engine import create_all_charts


BOT_TOKEN = "BURAYA_BOT_TOKEN"
CHAT_ID = "BURAYA_CHAT_ID"

BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
LAST_UPDATE_ID = None


def send_message(text):
    url = f"{BASE_URL}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": text[:3900]})


def send_photo(photo_path):
    url = f"{BASE_URL}/sendPhoto"
    with open(photo_path, "rb") as photo:
        requests.post(url, data={"chat_id": CHAT_ID}, files={"photo": photo})


def delete_webhook():
    try:
        requests.get(f"{BASE_URL}/deleteWebhook", timeout=10)
    except Exception:
        pass


def get_updates():
    global LAST_UPDATE_ID

    params = {"timeout": 10}
    if LAST_UPDATE_ID is not None:
        params["offset"] = LAST_UPDATE_ID + 1

    r = requests.get(f"{BASE_URL}/getUpdates", params=params, timeout=20)
    return r.json()


def process_message(text):
    text = text.strip()

    if not text.startswith("#"):
        return

    symbol = text.replace("#", "").strip().upper()

    if not symbol:
        send_message("Hisse kodu boş.")
        return

    send_message(f"{symbol} grafik hazırlanıyor...")

    try:
        files = create_all_charts(symbol)

        send_message(f"Oluşan dosyalar: {files}")

        if not files:
            send_message("Grafik oluşturulamadı.")
            return

        for file_path in files:
            send_message(f"Gönderiliyor: {file_path}")
            send_photo(file_path)

        send_message(f"{symbol} analiz tamamlandı.")

    except Exception:
        send_message(traceback.format_exc())


def main():
    global LAST_UPDATE_ID

    delete_webhook()
    send_message("GOKHAN_BIST_RADAR_PRO aktif. Komut bekliyorum.")

    while True:
        try:
            data = get_updates()

            if not data.get("ok"):
                send_message(f"Telegram getUpdates hatası: {data}")
                time.sleep(5)
                continue

            for item in data.get("result", []):
                LAST_UPDATE_ID = item["update_id"]

                msg = item.get("message", {})
                text = msg.get("text", "")

                if text:
                    process_message(text)

        except Exception:
            send_message(traceback.format_exc())

        time.sleep(2)


if __name__ == "__main__":
    main()