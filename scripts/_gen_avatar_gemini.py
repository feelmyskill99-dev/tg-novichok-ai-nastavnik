"""One-shot: 4 emblem candidates via Gemini (Nano Banana Pro). Saves to outputs/images/avatar_candidates/."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

import aiohttp
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.types import FSInputFile, InputMediaPhoto

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=ROOT / ".env")

PROMPT = (
    "Geometric flat emblem for a Telegram channel avatar. "
    "Single bold symbol: a stylized circular camera iris / aperture diaphragm with multiple geometric blades, "
    "and in the very center a single small japanese candlestick (one rectangular body with two thin wicks). "
    "Strictly no people, no faces, no humanoid figures, no hamsters, no animals, no chart lines on background. "
    "Absolutely no text, no letters, no numbers, no words anywhere in the image. "
    "Strictly no cyberpunk, no neon glow, no purple, no blue, no holograms, no sci-fi lighting. "
    "Color: warm amber / ochre accent on a dark charcoal (#1c1c1c) background. Two colors only, flat solid fills, no gradients. "
    "Style: minimal vector-style geometric icon, thick clean shapes, symmetrical, centered composition, readable as a tiny 40px circular avatar. "
    "Editorial graphic design, hand-illustrated feel, NOT corporate logo, NOT 3D render, NOT AI illustration. "
    "Solid dark background fills the entire square frame."
)


def _gen_one(client: genai.Client, out_path: Path) -> bool:
    try:
        resp = client.models.generate_content(
            model=os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image"),
            contents=[PROMPT],
            config=types.GenerateContentConfig(
                response_modalities=["TEXT", "IMAGE"],
            ),
        )
        for part in resp.parts:
            if part.inline_data:
                img = part.as_image()
                img.save(str(out_path), format="PNG")
                return True
        print(f"  no image part in response for {out_path.name}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"  {out_path.name} failed: {type(e).__name__}: {e}", file=sys.stderr)
        return False


class _ThreadedResolverSession(AiohttpSession):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._connector_init["resolver"] = aiohttp.ThreadedResolver()


async def _send(paths: list[Path]) -> None:
    token = (os.getenv("TELEGRAM_TOKEN") or "").strip()
    owner = (os.getenv("OWNER_CHAT_ID") or "").strip()
    if not token or not owner:
        print("TELEGRAM_TOKEN / OWNER_CHAT_ID empty — skipping send", file=sys.stderr)
        return
    caption = (
        "🖼 <b>AVATAR CANDIDATES — EMBLEM (Gemini Nano Banana Pro)</b>\n"
        "Концепция: диафрагма + свеча, охра на тёмно-сером, без людей и неона.\n\n"
        "Выбери номер (1–4) — поставлю через setup_channel."
    )
    bot = Bot(token=token, session=_ThreadedResolverSession())
    try:
        if len(paths) == 1:
            await bot.send_photo(owner, photo=FSInputFile(str(paths[0])), caption=caption, parse_mode=ParseMode.HTML)
        else:
            media = []
            for idx, p in enumerate(paths):
                if idx == 0:
                    media.append(InputMediaPhoto(media=FSInputFile(str(p)), caption=caption, parse_mode=ParseMode.HTML))
                else:
                    media.append(InputMediaPhoto(media=FSInputFile(str(p))))
            await bot.send_media_group(owner, media=media)
    finally:
        await bot.session.close()


def main() -> int:
    api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        print("GEMINI_API_KEY missing", file=sys.stderr)
        return 1
    client = genai.Client(api_key=api_key)

    out_dir = ROOT / "outputs" / "images" / "avatar_candidates"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("emblem_*.png"):
        old.unlink()

    successful: list[Path] = []
    for i in range(1, 5):
        out_path = out_dir / f"emblem_{i:02d}.png"
        print(f"generating {out_path.name}...")
        if _gen_one(client, out_path):
            successful.append(out_path)
            print(f"  saved: {out_path.relative_to(ROOT)}")

    if not successful:
        print("ALL 4 VARIANTS FAILED", file=sys.stderr)
        return 1

    asyncio.run(_send(successful))
    print(f"sent {len(successful)} variant(s) to OWNER_CHAT_ID")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
