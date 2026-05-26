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

import argparse
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
# rebranding 2026-05-26: новая версия (178 chars), утверждена в spec
# docs/superpowers/specs/2026-05-26-deposit-ai-rebranding-design.md
CHANNEL_DESCRIPTION = (
    "Учусь трейдингу публично. Маленький депозит, ошибки без прикрас "
    "и AI, который не даёт нажать кнопку в эмоции.\n\n"
    "Внутренний хомяк прилагается. Не сигналы, не гуру, не обещания.\n\n"
    "🐹🤖"
)


class _ThreadedResolverSession(AiohttpSession):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._connector_init["resolver"] = aiohttp.ThreadedResolver()


async def _run(*, avatar_only: bool, dry_run: bool, avatar_path: Path) -> int:
    token = (os.getenv("TELEGRAM_TOKEN") or "").strip()
    channel = (os.getenv("CHANNEL_ID") or "").strip()
    owner = (os.getenv("OWNER_CHAT_ID") or "").strip()

    if not token or not channel:
        print("TELEGRAM_TOKEN или CHANNEL_ID пустые", file=sys.stderr)
        return 1

    if not avatar_path.exists():
        print(f"avatar not found: {avatar_path}", file=sys.stderr)
        return 1

    desc = CHANNEL_DESCRIPTION
    if len(desc) > 255:
        desc = desc[:252].rstrip() + "..."

    if dry_run:
        print("=== DRY RUN ===")
        print(f"  channel:     {channel}")
        print(f"  avatar:      {avatar_path}  ({avatar_path.stat().st_size} bytes)")
        print(f"  title:       {CHANNEL_TITLE}")
        print(f"  description: ({len(desc)} chars)")
        for line in desc.splitlines():
            print(f"    | {line}")
        print(f"  avatar_only: {avatar_only}")
        if not avatar_only:
            print(f"  manifest:    YES (will be published and pinned)")
        else:
            print(f"  manifest:    NO (--avatar-only)")
        print("=== nothing was sent ===")
        return 0

    bot = Bot(token=token, session=_ThreadedResolverSession())
    report: list[str] = []
    try:
        try:
            await bot.set_chat_title(channel, title=CHANNEL_TITLE)
            report.append("setChatTitle: OK")
            print("setChatTitle: OK")
        except Exception as e:
            report.append(f"setChatTitle: FAIL ({type(e).__name__})")
            print(f"setChatTitle: FAIL {type(e).__name__}: {e}", file=sys.stderr)

        try:
            await bot.set_chat_description(channel, description=desc)
            report.append(f"setChatDescription: OK ({len(desc)} chars)")
            print(f"setChatDescription: OK ({len(desc)} chars)")
        except Exception as e:
            report.append(f"setChatDescription: FAIL ({type(e).__name__})")
            print(f"setChatDescription: FAIL {type(e).__name__}: {e}", file=sys.stderr)

        try:
            await bot.set_chat_photo(channel, photo=FSInputFile(str(avatar_path)))
            report.append("setChatPhoto: OK")
            print("setChatPhoto: OK")
        except Exception as e:
            report.append(f"setChatPhoto: FAIL ({type(e).__name__})")
            print(f"setChatPhoto: FAIL {type(e).__name__}: {e}", file=sys.stderr)

        if not avatar_only:
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

            if message_id:
                try:
                    await bot.pin_chat_message(channel, message_id=message_id,
                                              disable_notification=True)
                    report.append("pin manifest: OK")
                    print("pin manifest: OK")
                except Exception as e:
                    report.append(f"pin manifest: FAIL ({type(e).__name__}) — выдай боту can_pin_messages")
                    print(f"pin manifest: FAIL {type(e).__name__}: {e}", file=sys.stderr)

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


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Set up @ai_deposit_diary channel (title/desc/photo + optional manifest).")
    parser.add_argument("--avatar-only", action="store_true",
                        help="Только title + description + photo. Без публикации манифеста и закрепа.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Показать, что будет сделано, без обращения к Telegram API.")
    parser.add_argument("--avatar", type=Path,
                        default=ROOT / "outputs" / "images" / "channel_avatar.png",
                        help="Путь к файлу аватара (default: outputs/images/channel_avatar.png)")
    args = parser.parse_args()
    return asyncio.run(_run(
        avatar_only=args.avatar_only,
        dry_run=args.dry_run,
        avatar_path=args.avatar,
    ))


if __name__ == "__main__":
    sys.exit(main())
