"""Watchdog: проверяет health-status бота и шлёт DM владельцу при проблемах.

Запускать по cron раз в N часов:
    python tests/health_check.py

Этап 3.2: вся проверка делегирована в scripts/health_check.build_health_report.
Этот файл — только wrapper для рассылки DM.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
load_dotenv(ROOT / ".env")

from health_check import build_health_report  # noqa: E402

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID")


def send_telegram_message(text: str) -> None:
    if not TELEGRAM_TOKEN or not OWNER_CHAT_ID:
        print("Нет токена/OWNER_CHAT_ID, не могу отправить уведомление.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": OWNER_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        r = httpx.post(url, json=payload, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"Ошибка отправки уведомления: {e}")


def main() -> int:
    report = build_health_report()
    if report["ok"]:
        age = report["last_post_age_hours"]
        print(f"OK. last post {age}h назад, scheduler={report['scheduler_hint']}")
        return 0

    reasons: list[str] = []
    if report["scheduler_hint"] != "alive":
        reasons.append(f"scheduler={report['scheduler_hint']}")
    if report["post_stale"]:
        age = report["last_post_age_hours"]
        reasons.append(
            f"последний пост {age}h назад" if age is not None else "постов не было"
        )

    text = (
        "⚠️ <b>Watchdog: health-check failed</b>\n"
        f"Reasons: {', '.join(reasons) or 'unknown'}\n"
        f"Pending news drafts: {report['pending_news_drafts']}\n"
        f"Active confirm trades: {report['active_confirm_trades']}"
    )
    send_telegram_message(text)
    print(text)
    return 1


if __name__ == "__main__":
    sys.exit(main())
