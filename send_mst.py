import os
import requests

def msg_fun(message: str):
    """
    Sends a text message to a Telegram bot.
    Requires environment variable KEYS in the format: BOT_TOKEN_CHAT_ID
    Example:
      KEYS="123456789:ABCDEFghIJKLmnopQRSTUvwxYZ_987654321"
    """
    KEYS = os.getenv("KEYS")
    if not KEYS:
        raise ValueError("Environment variable 'KEYS' not found. Format: BOT_TOKEN_CHAT_ID")

    try:
        BOT_TOKEN, CHAT_ID = KEYS.split("-", 1)
    except ValueError:
        raise ValueError("Invalid KEYS format. Use BOT_TOKEN_CHAT_ID")

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    params = {"chat_id": CHAT_ID, "text": message}

    response = requests.get(url, params=params)
    data = response.json()

    if not data.get("ok"):
        print("❌ Failed to send message:", data)
    else:
        print("✅ Telegram message sent!")
    return data


def file_fun(file_path: str, caption: str = ""):
    """
    Sends a file (like .txt or .html) to a Telegram chat.
    Uses same KEYS environment variable as msg_fun.
    """
    if not os.path.exists(file_path):
        print(f"❌ File not found: {file_path}")
        return None

    KEYS = os.getenv("KEYS")
    if not KEYS:
        raise ValueError("Environment variable 'KEYS' not found. Format: BOT_TOKEN_CHAT_ID")

    try:
        BOT_TOKEN, CHAT_ID = KEYS.split("-", 1)
    except ValueError:
        raise ValueError("Invalid KEYS format. Use BOT_TOKEN_CHAT_ID")

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    with open(file_path, "rb") as f:
        files = {"document": f}
        data = {"chat_id": CHAT_ID, "caption": caption}
        response = requests.post(url, files=files, data=data)

    result = response.json()
    if not result.get("ok"):
        print("❌ Failed to send file:", result)
    else:
        print(f"✅ File sent successfully: {file_path}")
    return result
