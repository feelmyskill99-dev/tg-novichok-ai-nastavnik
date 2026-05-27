#!/usr/bin/env python3
"""setup_pinned_post.py — опубликовать и закрепить «О чём канал» пост.

Стартовый pinned-пост видят все, кто заходит в канал впервые. Сейчас в
канале нет закрепа → новый подписчик не понимает, о чём проект.

Что делает скрипт:
1. Собирает короткий приветственный пост (≤1000 символов, без photo, с
   разметкой Telegram HTML).
2. PARTNER_URL прогоняется через build_partner_url (utm_medium=pinned,
   utm_content=welcome) — это даёт track перехода именно из закрепа.
3. send_message в канал.
4. pinChatMessage с disable_notification=true (без шума у подписчиков).
5. Печатает message_id для записи в .env (PINNED_MESSAGE_ID — можно
   потом обновлять / снимать закреп вручную).

Запуск:
  python scripts/setup_pinned_post.py                # dry-run, печатает текст
  python scripts/setup_pinned_post.py --apply        # реально публикует и закрепляет
  python scripts/setup_pinned_post.py --dry-run-text  # только напечатать готовый HTML
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


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=ROOT / ".env")
sys.path.insert(0, str(ROOT))

from core.partner_link import build_partner_url  # noqa: E402


class _ThreadedResolverSession(AiohttpSession):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._connector_init["resolver"] = aiohttp.ThreadedResolver()


def _esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
    )


def build_pinned_html(partner_url: str = "") -> str:
    """Короткий приветственный пост. ≤1000 символов, без картинки.

    Структура:
    - заголовок,
    - 3 строки «что есть»,
    - 3 строки «чего нет»,
    - как работает (новичок + AI),
    - партнёрская ссылка (опц.),
    - дисклеймер + теги.
    """
    parts: list[str] = []
    parts.append("📌 <b>О чём этот канал</b>")
    parts.append("")
    parts.append("Я учусь трейдингу публично. Маленький депозит, ошибки без прикрас и AI, который не даёт нажать кнопку в эмоции.")
    parts.append("")
    parts.append("<b>Что здесь есть:</b>")
    parts.append("➤ Рыночные обзоры утром и обучение вечером.")
    parts.append("➤ Разборы новостей с конкретным «и что мне с этим делать».")
    parts.append("➤ Честные сделки с дневником — что чувствовал, где ошибся.")
    parts.append("")
    parts.append("<b>Чего здесь нет:</b>")
    parts.append("➤ Сигналов, гарантированных входов и «лучше брать сейчас».")
    parts.append("➤ Ракет, бычков, Lambo и обещаний прибыли.")
    parts.append("➤ Криптогуру с белыми зубами.")
    parts.append("")
    parts.append("🐹 <b>Новичок — это я.</b> Пишу, где внутренний хомяк уже тянется к кнопке.")
    parts.append("🤖 <b>AI-наставник — холодная часть.</b> Объясняет, где риск, где FOMO, где шум.")

    if partner_url:
        link = build_partner_url(partner_url, post_type="pinned", post_id="welcome")
        parts.append("")
        parts.append(f"📈 <b><a href=\"{_esc(link)}\">Я торгую здесь → Gate.io</a></b>")

    parts.append("")
    parts.append("<i>Не финсовет. Это дневник обучения и AI-разбор.</i>")
    parts.append("")
    parts.append("#честный_путь #новичок #ai_наставник")

    text = "\n".join(parts)
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text


async def _publish_and_pin(token: str, channel_id: str, text: str) -> int:
    bot = Bot(token=token, session=_ThreadedResolverSession())
    try:
        msg = await bot.send_message(
            channel_id, text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        try:
            await bot.pin_chat_message(
                channel_id, msg.message_id,
                disable_notification=True,
            )
        except Exception as e:
            print(f"WARN: не удалось закрепить (нужно can_pin_messages): {e}", file=sys.stderr)
        return msg.message_id
    finally:
        await bot.session.close()


async def _edit_existing(token: str, channel_id: str, message_id: int, text: str) -> None:
    bot = Bot(token=token, session=_ThreadedResolverSession())
    try:
        await bot.edit_message_text(
            chat_id=channel_id,
            message_id=message_id,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    finally:
        await bot.session.close()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Опубликовать и закрепить «О чём канал» пост")
    parser.add_argument("--apply", action="store_true",
                        help="реально публиковать и закрепить (по умолчанию dry-run)")
    parser.add_argument("--dry-run-text", action="store_true",
                        help="только напечатать собранный HTML")
    parser.add_argument("--edit", action="store_true",
                        help="отредактировать уже опубликованный pinned (PINNED_MESSAGE_ID из .env)")
    args = parser.parse_args()

    token = (os.getenv("TELEGRAM_TOKEN") or "").strip()
    channel_id = (os.getenv("CHANNEL_ID") or "").strip()
    partner_url = (os.getenv("PARTNER_URL") or "").strip()

    if not token or not channel_id:
        print("TELEGRAM_TOKEN или CHANNEL_ID не заданы в .env", file=sys.stderr)
        return 1

    text = build_pinned_html(partner_url)
    print("=== PINNED POST PREVIEW ===")
    print(text)
    print("===========================")
    print(f"length: {len(text)} chars (limit text 4096 / caption 1024)")

    if args.dry_run_text:
        return 0

    if args.edit:
        pinned_id_raw = (os.getenv("PINNED_MESSAGE_ID") or "").strip()
        if not pinned_id_raw.isdigit():
            print("PINNED_MESSAGE_ID не задан в .env — нечего редактировать", file=sys.stderr)
            return 1
        asyncio.run(_edit_existing(token, channel_id, int(pinned_id_raw), text))
        print()
        print(f"OK — отредактирован pinned message_id={pinned_id_raw}")
        return 0

    if not args.apply:
        print()
        print("DRY-RUN — ничего не отправлено. Запусти с --apply для публикации и закрепления.")
        return 0

    msg_id = asyncio.run(_publish_and_pin(token, channel_id, text))
    print()
    print(f"OK — опубликовано и закреплено, message_id={msg_id}")
    print(f"Сохрани в .env: PINNED_MESSAGE_ID={msg_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
