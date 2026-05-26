import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.safety import Sentinel


class _FakeBot:
    """Minimal stand-in для aiogram.Bot. Записывает все send_message-вызовы."""

    def __init__(self) -> None:
        self.calls: list[tuple[int | str, str, dict]] = []

    async def send_message(self, chat_id, text, **kwargs):
        self.calls.append((chat_id, text, dict(kwargs)))


def _make_fallback_file(tmp_path, items):
    p = tmp_path / "fallback.json"
    p.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return p


def _deep_raise_sync(depth: int):
    if depth > 0:
        _deep_raise_sync(depth - 1)
    else:
        raise ValueError("deep")


# ----------------------------------------------------------------------
# Constructor tests
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_init_loads_fallback_file(tmp_path):
    items = [
        {"title": "Урок 1", "body": "Текст урока 1"},
        {"title": "Урок 2", "body": "Текст урока 2"},
    ]
    fp = _make_fallback_file(tmp_path, items)
    bot = _FakeBot()
    sentinel = Sentinel(bot, "@chan", 123, fallback_file=str(fp))
    assert sentinel.fallback_posts == items


@pytest.mark.asyncio
async def test_init_empty_fallback_raises(tmp_path):
    fp = _make_fallback_file(tmp_path, [])
    bot = _FakeBot()
    with pytest.raises(ValueError):
        Sentinel(bot, "@chan", 123, fallback_file=str(fp))


@pytest.mark.asyncio
async def test_init_missing_file_raises(tmp_path):
    nonexistent = tmp_path / "nonexistent.json"
    bot = _FakeBot()
    with pytest.raises(FileNotFoundError):
        Sentinel(bot, "@chan", 123, fallback_file=str(nonexistent))


# ----------------------------------------------------------------------
# safe_execute – happy path
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_safe_execute_runs_coro_normally(tmp_path):
    items = [{"title": "T", "body": "B"}]
    fp = _make_fallback_file(tmp_path, items)
    bot = _FakeBot()
    sentinel = Sentinel(bot, "@chan", 123, fallback_file=str(fp))

    counter = 0

    async def good_coro():
        nonlocal counter
        counter = 1

    await sentinel.safe_execute(good_coro())
    assert counter == 1
    assert bot.calls == []


@pytest.mark.asyncio
async def test_safe_execute_returns_none_on_success(tmp_path):
    items = [{"title": "T", "body": "B"}]
    fp = _make_fallback_file(tmp_path, items)
    bot = _FakeBot()
    sentinel = Sentinel(bot, "@chan", 123, fallback_file=str(fp))

    async def good_coro():
        pass

    result = await sentinel.safe_execute(good_coro())
    assert result is None


# ----------------------------------------------------------------------
# safe_execute – error path
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_safe_execute_sends_dm_on_exception(tmp_path):
    items = [{"title": "T", "body": "B"}]
    fp = _make_fallback_file(tmp_path, items)
    bot = _FakeBot()
    sentinel = Sentinel(bot, "@chan", 123, fallback_file=str(fp))

    async def failing_coro():
        raise RuntimeError("boom")

    await sentinel.safe_execute(failing_coro())
    assert len(bot.calls) >= 1
    dm_call = bot.calls[0]
    assert dm_call[0] == 123
    text = dm_call[1]
    assert "СБОЙ" in text
    assert "RuntimeError" in text
    assert "boom" in text


@pytest.mark.asyncio
async def test_safe_execute_publishes_fallback_to_channel(tmp_path):
    items = [{"title": "Урок 1", "body": "Текст урока 1"}]
    fp = _make_fallback_file(tmp_path, items)
    bot = _FakeBot()
    sentinel = Sentinel(bot, "@chan", 123, fallback_file=str(fp))

    async def failing_coro():
        raise RuntimeError("boom")

    await sentinel.safe_execute(failing_coro())
    channel_call = bot.calls[1]
    assert channel_call[0] == "@chan"
    assert "Урок 1\n\nТекст урока 1" in channel_call[1]


@pytest.mark.asyncio
async def test_safe_execute_two_calls_on_failure(tmp_path):
    items = [{"title": "T", "body": "B"}]
    fp = _make_fallback_file(tmp_path, items)
    bot = _FakeBot()
    sentinel = Sentinel(bot, "@chan", 123, fallback_file=str(fp))

    async def failing_coro():
        raise RuntimeError("boom")

    await sentinel.safe_execute(failing_coro())
    assert len(bot.calls) == 2


@pytest.mark.asyncio
async def test_safe_execute_passes_context_in_dm(tmp_path):
    items = [{"title": "T", "body": "B"}]
    fp = _make_fallback_file(tmp_path, items)
    bot = _FakeBot()
    sentinel = Sentinel(bot, "@chan", 123, fallback_file=str(fp))

    async def failing_coro():
        raise RuntimeError("boom")

    await sentinel.safe_execute(failing_coro(), context="news_publish")
    dm_text = bot.calls[0][1]
    assert "news_publish" in dm_text


@pytest.mark.asyncio
async def test_safe_execute_no_context_uses_default(tmp_path):
    items = [{"title": "T", "body": "B"}]
    fp = _make_fallback_file(tmp_path, items)
    bot = _FakeBot()
    sentinel = Sentinel(bot, "@chan", 123, fallback_file=str(fp))

    async def failing_coro():
        raise RuntimeError("boom")

    await sentinel.safe_execute(failing_coro())
    dm_text = bot.calls[0][1]
    assert "неизвестно" in dm_text


@pytest.mark.asyncio
async def test_safe_execute_truncates_long_traceback(tmp_path):
    items = [{"title": "T", "body": "B"}]
    fp = _make_fallback_file(tmp_path, items)
    bot = _FakeBot()
    sentinel = Sentinel(bot, "@chan", 123, fallback_file=str(fp))

    async def deep_failing_coro():
        _deep_raise_sync(50)

    await sentinel.safe_execute(deep_failing_coro())
    dm_text = bot.calls[0][1]
    assert "```" in dm_text
    assert len(dm_text) < 4000


@pytest.mark.asyncio
async def test_safe_execute_traceback_in_markdown_code_block(tmp_path):
    items = [{"title": "T", "body": "B"}]
    fp = _make_fallback_file(tmp_path, items)
    bot = _FakeBot()
    sentinel = Sentinel(bot, "@chan", 123, fallback_file=str(fp))

    async def failing_coro():
        raise RuntimeError("boom")

    await sentinel.safe_execute(failing_coro())
    dm_text = bot.calls[0][1]
    assert dm_text.count("```") >= 2  # opening and closing (or more)


# ----------------------------------------------------------------------
# Random fallback selection
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fallback_post_is_one_of_loaded(tmp_path):
    lessons = [
        {"title": f"Урок {i}", "body": f"Текст урока {i}"} for i in range(1, 6)
    ]
    fp = _make_fallback_file(tmp_path, lessons)
    bot = _FakeBot()
    sentinel = Sentinel(bot, "@chan", 123, fallback_file=str(fp))

    expected_texts = {f"{l['title']}\n\n{l['body']}" for l in lessons}

    async def failing_coro():
        raise RuntimeError("boom")

    for _ in range(10):
        await sentinel.safe_execute(failing_coro())

    # Все channel‑публикации (каждый второй call) должны быть среди шаблонов
    for i in range(1, len(bot.calls), 2):
        channel_text = bot.calls[i][1]
        assert channel_text in expected_texts


@pytest.mark.asyncio
async def test_fallback_includes_title_and_body(tmp_path):
    lesson = {"title": "T", "body": "B"}
    fp = _make_fallback_file(tmp_path, [lesson])
    bot = _FakeBot()
    sentinel = Sentinel(bot, "@chan", 123, fallback_file=str(fp))

    async def failing_coro():
        raise RuntimeError("boom")

    await sentinel.safe_execute(failing_coro())
    channel_text = bot.calls[1][1]
    assert "T" in channel_text
    assert "B" in channel_text