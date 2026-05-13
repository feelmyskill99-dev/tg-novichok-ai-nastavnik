"""
Автотест здоровья бота.
Запускать по cron раз в день или чаще.
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
import httpx

# Добавляем корень проекта в путь, чтобы импортировать load_dotenv и конфиги
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID")

STATE_FILE = ROOT / "state.json"
HISTORY_FILE = ROOT / "history.json"
MAX_SILENCE_HOURS = 12  # если бот молчит дольше этого — слать тревогу


def send_telegram_message(text: str):
    """Отправляет сообщение владельцу через Telegram Bot API."""
    if not TELEGRAM_TOKEN or not OWNER_CHAT_ID:
        print("Нет токена/OWNER_CHAT_ID, не могу отправить уведомление.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": OWNER_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        r = httpx.post(url, json=payload, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"Ошибка отправки уведомления: {e}")


def check_last_post_time() -> datetime | None:
    """Возвращает время последнего поста из history.json."""
    if not HISTORY_FILE.exists():
        return None
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        if not data:
            return None
        last_entry = data[-1]
        ts = last_entry.get("datetime")
        if ts:
            return datetime.fromisoformat(ts)
    except Exception as e:
        print(f"Ошибка чтения истории: {e}")
    return None


def main():
    now = datetime.now(tz=timezone.utc)
    last_post = check_last_post_time()
    if last_post is None:
        send_telegram_message("🚨 <b>Мониторинг</b>: нет записей в history.json. Бот, возможно, не запущен или не публиковал посты.")
        return

    silence = now - last_post
    hours_silent = silence.total_seconds() / 3600
    if hours_silent > MAX_SILENCE_HOURS:
        text = (
            f"⚠️ <b>Бот молчит уже {hours_silent:.1f} часов!</b>\n"
            f"Последний пост был: {last_post.strftime('%Y-%m-%d %H:%M UTC')}\n"
            "Проверьте работу планировщика или API."
        )
        send_telegram_message(text)
    else:
        print(f"Бот активен. Последний пост {hours_silent:.1f} ч. назад — всё в порядке.")


if __name__ == "__main__":
    main()