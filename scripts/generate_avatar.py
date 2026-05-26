"""Генерирует 4 варианта эмблемы канала через OpenAI API и отправляет владельцу."""

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
from aiogram.types import FSInputFile, InputMediaPhoto
from openai import OpenAI


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=ROOT / ".env")


PROMPT = (
    "Geometric emblem, single symbol, no people, no humanoid figures, "
    "no hamsters, no animals, no chart background, no text, no letters, "
    "no cyberpunk, no neon. "
    "Stylized aperture / iris diaphragm with a single japanese candlestick at the center. "
    "Warm amber or ochre accent on dark charcoal background, two colors only. "
    "Minimal vector-style geometric design, flat, readable at 40px. "
    "Centered composition for a circular Telegram avatar."
)


class _ThreadedResolverSession(AiohttpSession):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._connector_init["resolver"] = aiohttp.ThreadedResolver()


def _generate_image(out_path: Path) -> str:
    """Сохраняет файл и возвращает имя модели ('gpt-image-2'/'gpt-image-1')."""
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


async def _send_to_owner(paths: list[Path], models: list[str]) -> None:
    token = (os.getenv("TELEGRAM_TOKEN") or "").strip()
    owner = (os.getenv("OWNER_CHAT_ID") or "").strip()
    if not token or not owner:
        print("TELEGRAM_TOKEN или OWNER_CHAT_ID пустые — отправка пропущена", file=sys.stderr)
        return

    model_str = ", ".join(sorted(set(models)))
    # Общая часть подписи
    caption = (
        "🖼 [AVATAR CANDIDATES — EMBLEM]\n"
        f"Модель: <code>{model_str}</code>\n"
        f"Файлы: outputs/images/avatar_candidates/emblem_*.png\n\n"
        "Выбери номер (1–4), и я поставлю через setChatPhoto."
    )

    bot = Bot(token=token, session=_ThreadedResolverSession())
    try:
        if len(paths) == 1:
            await bot.send_photo(
                owner,
                photo=FSInputFile(str(paths[0])),
                caption=caption,
                parse_mode=ParseMode.HTML,
            )
        else:
            media = []
            for idx, p in enumerate(paths):
                if idx == 0:
                    media.append(
                        InputMediaPhoto(
                            media=FSInputFile(str(p)),
                            caption=caption,
                            parse_mode=ParseMode.HTML,
                        )
                    )
                else:
                    media.append(InputMediaPhoto(media=FSInputFile(str(p))))
            await bot.send_media_group(owner, media=media)
    finally:
        await bot.session.close()


def main() -> int:
    out_dir = ROOT / "outputs" / "images" / "avatar_candidates"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Очистка старых emblem_*.png
    for old in out_dir.glob("emblem_*.png"):
        old.unlink()

    successful: list[Path] = []
    models_used: list[str] = []

    for i in range(1, 5):
        out_path = out_dir / f"emblem_{i:02d}.png"
        try:
            model = _generate_image(out_path)
            successful.append(out_path)
            models_used.append(model)
            print(f"generated: {out_path.relative_to(ROOT)} (model: {model})")
        except Exception as e:
            print(f"failed emblem_{i:02d}: {type(e).__name__}: {e}", file=sys.stderr)

    if not successful:
        print("ALL 4 VARIANTS FAILED", file=sys.stderr)
        return 1

    asyncio.run(_send_to_owner(successful, models_used))
    print(f"sent {len(successful)} variant(s) to OWNER_CHAT_ID")
    return 0


if __name__ == "__main__":
    sys.exit(main())