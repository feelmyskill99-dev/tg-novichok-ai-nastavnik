"""Авто-оформление канала @ai_deposit_diary.

Делает:
  1. setChatTitle    — название канала
  2. setChatDescription — описание (plain text, до 255 символов)
  3. setChatPhoto    — аватар из outputs/images/channel_avatar.png
  4. send manifest   — публикует манифест в канал (это первый пост канала)
  5. pin manifest    — пытается закрепить; если права нет — пишет в OWNER,
                       чтобы владелец дал can_pin_messages.

Бот должен быть admin с правами:
  can_change_info     (для title/description/photo)
  can_post_messages   (для публикации)
  can_pin_messages    (для закрепа; опционально — если нет, пользователю предложим)
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
from aiogram.types import FSInputFile


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=ROOT / ".env")

# импортируем готовый текст манифеста из starter-pack (без дублирования)
sys.path.insert(0, str(ROOT / "scripts"))
from send_starter_posts import post_1_manifest   # noqa: E402


CHANNEL_TITLE = "Депозит под надзором ИИ"
# Telegram channel description: plain text, до 255 символов.
CHANNEL_DESCRIPTION = (
    "Честный дневник трейдера-новичка под надзором ИИ 🤖\n\n"
    "Маленький депозит, ошибки без прикрас, риск-менеджмент, новости "
    "и внутренний хомяк 🐹\n\n"
    "Без сигналов, гуру и обещаний прибыли."
)


class _ThreadedResolverSession(AiohttpSession):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._connector_init["resolver"] = aiohttp.ThreadedResolver()


async def main() -> int:
    token = (os.getenv("TELEGRAM_TOKEN") or "").strip()
    channel = (os.getenv("CHANNEL_ID") or "").strip()
    owner = (os.getenv("OWNER_CHAT_ID") or "").strip()

    if not token or not channel:
        print("TELEGRAM_TOKEN или CHANNEL_ID пустые", file=sys.stderr)
        return 1

    avatar = ROOT / "outputs" / "images" / "channel_avatar.png"
    if not avatar.exists():
        print(f"avatar not found: {avatar}", file=sys.stderr)
        return 1

    bot = Bot(token=token, session=_ThreadedResolverSession())
    report: list[str] = []
    try:
        # 1. title
        try:
            await bot.set_chat_title(channel, title=CHANNEL_TITLE)
            report.append("setChatTitle: OK")
            print("setChatTitle: OK")
        except Exception as e:
            report.append(f"setChatTitle: FAIL ({type(e).__name__})")
            print(f"setChatTitle: FAIL {type(e).__name__}: {e}", file=sys.stderr)

        # 2. description (plain text, len ≤ 255)
        desc = CHANNEL_DESCRIPTION
        if len(desc) > 255:
            desc = desc[:252].rstrip() + "..."
        try:
            await bot.set_chat_description(channel, description=desc)
            report.append(f"setChatDescription: OK ({len(desc)} chars)")
            print(f"setChatDescription: OK ({len(desc)} chars)")
        except Exception as e:
            report.append(f"setChatDescription: FAIL ({type(e).__name__})")
            print(f"setChatDescription: FAIL {type(e).__name__}: {e}", file=sys.stderr)

        # 3. photo
        try:
            await bot.set_chat_photo(channel, photo=FSInputFile(str(avatar)))
            report.append("setChatPhoto: OK")
            print("setChatPhoto: OK")
        except Exception as e:
            report.append(f"setChatPhoto: FAIL ({type(e).__name__})")
            print(f"setChatPhoto: FAIL {type(e).__name__}: {e}", file=sys.stderr)

        # 4. publish manifest
        manifest = post_1_manifest()
        message_id = None
        try:
            msg = await bot.send_message(
                channel, manifest,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            message_id = msg.message_id
            report.append(f"manifest published: message_id={message_id}")
            print(f"manifest published: message_id={message_id}")
        except Exception as e:
            report.append(f"send manifest: FAIL ({type(e).__name__})")
            print(f"send manifest: FAIL {type(e).__name__}: {e}", file=sys.stderr)

        # 5. pin (best effort)
        if message_id:
            try:
                await bot.pin_chat_message(channel, message_id=message_id,
                                          disable_notification=True)
                report.append("pin manifest: OK")
                print("pin manifest: OK")
            except Exception as e:
                report.append(f"pin manifest: FAIL ({type(e).__name__}) — выдай боту can_pin_messages в Settings → Administrators")
                print(f"pin manifest: FAIL {type(e).__name__}: {e}", file=sys.stderr)

        # 6. отчёт владельцу
        if owner:
            try:
                summary = (
                    "<b>📦 [CHANNEL SETUP]</b>\n\n"
                    + "\n".join(f"• {line}" for line in report)
                )
                await bot.send_message(owner, summary, parse_mode=ParseMode.HTML)
            except Exception as e:
                print(f"owner notify failed: {e}", file=sys.stderr)
    finally:
        await bot.session.close()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
