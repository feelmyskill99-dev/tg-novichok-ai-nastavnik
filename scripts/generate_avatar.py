"""Генерирует аватар канала через OpenAI Image API и шлёт владельцу для ручной установки.

Сохраняет:
    outputs/images/channel_avatar.png

Не пытается ставить аватар через Telegram API автоматически — спецификация требует
ручной установки. Просто отправляет файл OWNER_CHAT_ID.
"""

from __future__ import annotations

import asyncio
import base64
import os
import sys
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

import aiohttp
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.types import FSInputFile
from openai import OpenAI


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=ROOT / ".env")


PROMPT = (
    "A circular Telegram avatar for a Russian crypto learning diary channel. "
    "A nervous beginner trader sits in front of a dark crypto chart, while a calm "
    "AI mentor hologram observes and analyzes the screen. "
    "Mood: honest, cinematic, intelligent, not luxury, not aggressive. "
    "Dark cyberpunk minimalism, blue-gray neon tones, subtle red and green candle "
    "chart glow. No bulls, no rockets, no money rain, no text, no letters. "
    "Clean icon composition, readable at small size."
)


class _ThreadedResolverSession(AiohttpSession):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._connector_init["resolver"] = aiohttp.ThreadedResolver()


def _generate_image(out_path: Path) -> str:
    """Возвращает 'gpt-image-2'/'gpt-image-1' — какой модели удалось.

    Сохраняет файл в out_path.
    """
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY не задан")
    primary = (os.getenv("IMAGE_MODEL") or "gpt-image-2").strip()
    fallback = (os.getenv("IMAGE_MODEL_FALLBACK") or "gpt-image-1").strip()
    client = OpenAI(api_key=api_key)
    last_err: Exception | None = None
    for model in [m for m in (primary, fallback) if m]:
        try:
            r = client.images.generate(model=model, prompt=PROMPT, size="1024x1024")
            d = r.data[0]
            b64 = getattr(d, "b64_json", None)
            url = getattr(d, "url", None)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            if b64:
                out_path.write_bytes(base64.b64decode(b64))
            elif url:
                urllib.request.urlretrieve(url, str(out_path))
            else:
                raise RuntimeError("OpenAI ответ без b64_json и без url")
            return model
        except Exception as e:
            last_err = e
            print(f"image model {model} не сработал: {type(e).__name__}: {e}", file=sys.stderr)
    raise RuntimeError(f"all image models failed: {last_err}")


async def _send_to_owner(image_path: Path, model_used: str) -> None:
    token = (os.getenv("TELEGRAM_TOKEN") or "").strip()
    owner = (os.getenv("OWNER_CHAT_ID") or "").strip()
    if not token or not owner:
        print("TELEGRAM_TOKEN или OWNER_CHAT_ID пустые — отправка пропущена", file=sys.stderr)
        return

    bot = Bot(token=token, session=_ThreadedResolverSession())
    try:
        caption = (
            "<b>🖼 [CHANNEL AVATAR]</b>\n"
            f"Сгенерировано через <code>{model_used}</code>.\n"
            f"Файл сохранён: <code>outputs/images/channel_avatar.png</code>\n\n"
            "Установи вручную в Telegram: "
            "<i>Settings → Edit channel → Photo → выбрать файл</i>.\n"
            "Автоматическая установка через Bot API не используется (по спецификации)."
        )
        await bot.send_photo(
            owner,
            photo=FSInputFile(str(image_path)),
            caption=caption,
            parse_mode=ParseMode.HTML,
        )
    finally:
        await bot.session.close()


def main() -> int:
    out = ROOT / "outputs" / "images" / "channel_avatar.png"
    try:
        model_used = _generate_image(out)
    except Exception as e:
        print(f"AVATAR GENERATION FAILED: {type(e).__name__}", file=sys.stderr)
        return 1
    print(f"saved: {out.relative_to(ROOT)}")
    print(f"model: {model_used}")
    asyncio.run(_send_to_owner(out, model_used))
    print("sent to OWNER_CHAT_ID")
    return 0


if __name__ == "__main__":
    sys.exit(main())
