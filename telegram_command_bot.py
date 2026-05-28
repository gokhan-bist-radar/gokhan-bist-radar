import json
import os
import requests
import traceback

from chart_engine import create_all_charts


BOT_TOKEN = "BURAYA_BOT_TOKEN"
CHAT_ID = "BURAYA_CHAT_ID"

BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
STATE_FILE = "last_update_id.txt"


def send_message(text):
    requests.post(
        f"{BASE_URL}/sendMessage",
        data={"chat_id": CHAT_ID, "text": str(text)[:3900]},
        timeout=30
    )


def send_photo(photo_path):
    with open(photo_path, "rb") as photo:
        requests.post(
            f"{BASE_URL}/sendPhoto",
            data={"chat_id": CHAT_ID},
            files={"photo": photo},
            timeout=60
        )


def read_last_update_id():
    if not os.path.exists(STATE_FILE):
        return None
    try:
        with open(STATE_FILE, "r") as f:
            return int(f.read().strip())
    except Exception:
        return None


def write_last_update_id(update_id):
    with open(STATE_FILE, "w") as f:
        f.write(str(update_id))


def delete_webhook():
    requests.get(f"{BASE_URL}/deleteWebhook", timeout=20)


def get_updates():
    last_id = read_last_update_id()
    params = {"timeout": 1}

    if last_id is not None:
        params["offset"] = last_id + 1

    r = requests.get(f"{BASE_URL}/getUpdates", params=params, timeout=20)
    return r.json()


def handle_symbol(symbol):
    send_message(f"{symbol} grafik hazırlanıyor...")

    files = create_all_charts(symbol)

    send_message(f"Oluşan dosyalar: {files}")

    if not files:
        send_message("Grafik oluşturulamadı.")
        return

    for file_path in files:
        send_message(f"Gönderiliyor: {file_path}")
        send_photo(file_path)

    send_message(f"{symbol} analiz tamamlandı.")


def main():
    try:
        delete_webhook()

        data = get_updates()

        if not data.get("ok"):
            send_message(f"getUpdates hatası: {data}")
            return

        results = data.get("result", [])

        if not results:
            send_message("Yeni komut yok.")
            return

        for item in results:
            update_id = item.get("update_id")
            write_last_update_id(update_id)

            msg = item.get("message", {})
            chat = msg.get("chat", {})
            text = msg.get("text", "")

            if str(chat.get("id")) != str(CHAT_ID):
                continue

            if text.startswith("#"):
                symbol = text.replace("#", "").strip().upper()
                handle_symbol(symbol)

    except Exception:
        send_message(traceback.format_exc())


if __name__ == "__main__":
    main()