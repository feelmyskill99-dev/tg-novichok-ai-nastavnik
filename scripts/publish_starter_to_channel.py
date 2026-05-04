"""Публикует 3 учебных поста (#2, #3, #4) непосредственно в канал.

Манифест (#1) уже там — закреплён. Этот скрипт добавляет образовательную базу,
чтобы канал не висел пустым с одним только закрепом.

В планировщике DRY_RUN=true → контент-посты по расписанию идут в OWNER. Это разовая
явная публикация в канал, не через scheduler.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

import aiohttp
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=ROOT / ".env")
sys.path.insert(0, str(ROOT / "scripts"))

from send_starter_posts import (   # noqa: E402
    post_2_how_to_read,
    post_3_why_no_x20,
    post_4_risk_per_trade,
)


class _ThreadedResolverSession(AiohttpSession):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._connector_init["resolver"] = aiohttp.ThreadedResolver()


# Пауза между постами — небольшая (канал пустой, UX-проблем нет, но дадим
# Telegram время на link previews и не упрёмся в rate-limit).
DELAY_BETWEEN_POSTS_SEC = 8.0


async def main() -> int:
    token = (os.getenv("TELEGRAM_TOKEN") or "").strip()
    channel = (os.getenv("CHANNEL_ID") or "").strip()
    owner = (os.getenv("OWNER_CHAT_ID") or "").strip()
    if not token or not channel:
        print("TELEGRAM_TOKEN или CHANNEL_ID пустые", file=sys.stderr)
        return 1

    bot = Bot(token=token, session=_ThreadedResolverSession())
    posts = [
        ("Post 2: Как читать дневник", post_2_how_to_read()),
        ("Post 3: Почему не фьючерсы x20", post_3_why_no_x20()),
        ("Post 4: Риск на сделку", post_4_risk_per_trade()),
    ]
    report: list[str] = []
    try:
        for label, text in posts:
            print(f"-> publishing: {label}")
            try:
                msg = await bot.send_message(
                    channel, text,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
                print(f"   ok: message_id={msg.message_id}")
                report.append(f"{label} — message_id={msg.message_id}")
            except Exception as e:
                print(f"   FAIL: {type(e).__name__}: {e}", file=sys.stderr)
                report.append(f"{label} — FAIL ({type(e).__name__})")
            await asyncio.sleep(DELAY_BETWEEN_POSTS_SEC)

        if owner:
            try:
                summary = (
                    "<b>📦 [STARTER PACK PUBLISHED]</b>\n\n"
                    + "\n".join(f"• {line}" for line in report)
                    + "\n\nКанал теперь имеет манифест (закреплён) + 3 учебных поста."
                )
                await bot.send_message(owner, summary, parse_mode=ParseMode.HTML)
            except Exception as e:
                print(f"owner notify failed: {e}", file=sys.stderr)
    finally:
        await bot.session.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
