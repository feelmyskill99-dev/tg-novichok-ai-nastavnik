"""Превью новостного поста владельцу: header слит в caption.

Контракт:
- header inline (<i>🧪 #id · impact N · sector · tone</i>) встраивается
  в начало text'а одним сообщением.
- если image+combined > 1024 → header отдельно, сам пост без header'а.
- guard-блок (если есть guard_reasons) шлётся отдельным сообщением ДО поста.
- meta=None → ничего лишнего не добавляется, идёт чистый text.
"""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Без OWNER_CHAT_ID функция отваливается — выставим до импорта bot
os.environ.setdefault("OWNER_CHAT_ID", "999000")

import bot  # noqa: E402


@pytest.fixture
def fake_bot():
    b = MagicMock()
    b.send_message = AsyncMock()
    b.send_photo = AsyncMock()
    return b


@pytest.fixture
def captured():
    """Перехватывает вызов send_post_with_optional_image и пишет args."""
    calls: list[dict] = []

    async def _stub(bot, chat_id, post_html, image_path=None, **kwargs):
        calls.append({
            "chat_id": chat_id,
            "post_html": post_html,
            "image_path": image_path,
            **kwargs,
        })

    with patch.object(bot, "send_post_with_optional_image", side_effect=_stub):
        yield calls


@pytest.mark.asyncio
async def test_header_merged_into_caption_when_under_limit(fake_bot, captured):
    text = "<b>Title</b>\n\nLead text\n\n➤ fact 1\n➤ fact 2"
    meta = {
        "draft_id": "abcdef1234567890",
        "sector": "ai_crypto",
        "impact": 95,
        "tone": "calm",
    }
    await bot._news_preview_send(fake_bot, text, kb_dict={}, image_path=None, meta=meta)

    # header пошёл ВНУТРИ post_html, отдельных send_message от хелпера нет
    assert fake_bot.send_message.call_count == 0, "header не должен идти отдельным сообщением"
    assert len(captured) == 1
    combined = captured[0]["post_html"]
    assert "🧪 #abcdef12" in combined
    assert "impact 95" in combined
    assert "ai_crypto" in combined
    assert "calm" in combined
    # после header — пустая строка, потом сам text
    assert combined.startswith("<i>")
    assert text in combined


@pytest.mark.asyncio
async def test_no_meta_no_header(fake_bot, captured):
    text = "<b>Some post</b>\n\nbody"
    await bot._news_preview_send(fake_bot, text, kb_dict={}, image_path=None, meta=None)

    assert len(captured) == 1
    assert captured[0]["post_html"] == text   # никакого header'а
    assert fake_bot.send_message.call_count == 0


@pytest.mark.asyncio
async def test_guard_reasons_sent_separately(fake_bot, captured):
    text = "<b>Title</b>\nbody"
    meta = {
        "draft_id": "deadbeef",
        "sector": "scam_radar",
        "impact": 100,
        "tone": "harsh",
        "guard_reasons": ["specific_title пустой", "tone невалидный"],
    }
    await bot._news_preview_send(fake_bot, text, kb_dict={}, image_path=None, meta=meta)

    # guard ушёл отдельным сообщением (1 вызов send_message)
    assert fake_bot.send_message.call_count == 1
    guard_call = fake_bot.send_message.call_args
    assert "Publish-guard" in guard_call.args[1] or "Publish-guard" in str(guard_call.kwargs.get("text", ""))
    # обе причины в тексте
    sent = guard_call.args[1]
    assert "specific_title пустой" in sent
    assert "tone невалидный" in sent

    # сам пост ушёл одним вызовом с inline header'ом
    assert len(captured) == 1
    assert "🧪 #deadbeef" in captured[0]["post_html"]


@pytest.mark.asyncio
async def test_caption_overflow_fallback_to_separate_header(fake_bot, captured, tmp_path):
    """Если image+combined > 1024 — header едет отдельно, пост чистый."""
    # имитируем существующий файл картинки
    img = tmp_path / "fake.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)

    long_text = "<b>T</b>\n" + ("x" * 1010)  # сам по себе впритык
    meta = {
        "draft_id": "abcd1234",
        "sector": "macro",
        "impact": 80,
        "tone": "confused",
    }
    await bot._news_preview_send(
        fake_bot, long_text, kb_dict={}, image_path=str(img), meta=meta,
    )

    # header отдельным сообщением
    assert fake_bot.send_message.call_count == 1
    header_sent = fake_bot.send_message.call_args.args[1]
    assert "🧪 #abcd1234" in header_sent

    # сам пост — без вшитого header'а
    assert len(captured) == 1
    assert captured[0]["post_html"] == long_text
    assert not captured[0]["post_html"].startswith("<i>")


@pytest.mark.asyncio
async def test_short_caption_with_image_still_merged(fake_bot, captured, tmp_path):
    """Короткий пост + image → header всё равно сливается (combined <= 1024)."""
    img = tmp_path / "fake.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)

    text = "<b>Short</b>\n\nbody"
    meta = {"draft_id": "11112222", "sector": "ai_crypto", "impact": 90, "tone": "calm"}
    await bot._news_preview_send(
        fake_bot, text, kb_dict={}, image_path=str(img), meta=meta,
    )

    assert fake_bot.send_message.call_count == 0  # никаких отдельных сообщений
    assert len(captured) == 1
    assert "🧪 #11112222" in captured[0]["post_html"]
    assert captured[0]["image_path"] == str(img)
