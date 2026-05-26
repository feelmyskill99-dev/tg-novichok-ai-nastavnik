#!/usr/bin/env python3
"""channel_stats.py — базовая аналитика канала @ai_deposit_diary."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

import aiohttp
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.json_store import load_json  # noqa: E402
from core.content_mix_writer import append_channel_stats  # noqa: E402

STATE_PATH = ROOT / "state.json"


class _ThreadedResolverSession(AiohttpSession):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._connector_init["resolver"] = aiohttp.ThreadedResolver()


async def _collect_stats(token: str, channel_id: str) -> dict:
    bot = Bot(token=token, session=_ThreadedResolverSession())
    stats: dict = {}

    try:
        subscribers_count = await bot.get_chat_member_count(channel_id)
        stats["subscribers_count"] = subscribers_count
    except Exception:
        stats["subscribers_count"] = None

    try:
        chat = await bot.get_chat(channel_id)
        stats["channel_title"] = chat.title
    except Exception:
        stats["channel_title"] = None

    try:
        bot_member = await bot.get_chat_member(channel_id, bot.id)
        stats["bot_can_post"] = getattr(bot_member, "can_post_messages", None)
    except AttributeError:
        stats["bot_can_post"] = None
    except Exception:
        stats["bot_can_post"] = None

    await bot.session.close()

    now_utc = datetime.now(timezone.utc)
    history = load_json(ROOT / "history.json", default=[], expected_type=list)
    posts_last_7d = 0
    posts_last_30d = 0
    if isinstance(history, list):
        for entry in history:
            ts_str = entry.get("datetime") if isinstance(entry, dict) else None
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if ts >= now_utc - timedelta(days=7):
                        posts_last_7d += 1
                    if ts >= now_utc - timedelta(days=30):
                        posts_last_30d += 1
                except Exception:
                    pass
    stats["posts_last_7d"] = posts_last_7d
    stats["posts_last_30d"] = posts_last_30d

    news_drafts = load_json(ROOT / "news_drafts.json", default=[], expected_type=list)
    author_notes = load_json(ROOT / "author_notes_drafts.json", default=[], expected_type=list)
    weekly_diary = load_json(ROOT / "weekly_diary_drafts.json", default=[], expected_type=list)
    stats["pending_drafts"] = {
        "news": len(news_drafts) if isinstance(news_drafts, list) else 0,
        "author_notes": len(author_notes) if isinstance(author_notes, list) else 0,
        "weekly_diary": len(weekly_diary) if isinstance(weekly_diary, list) else 0,
    }

    confirm_trades = load_json(ROOT / "confirm_trades.json", default={}, expected_type=dict)
    stats["active_confirm_trades"] = len(confirm_trades) if isinstance(confirm_trades, dict) else 0

    return stats


def _fmt(val, alt: str = "n/a"):
    if val is None:
        return alt
    return str(val)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Сбор метрик канала @ai_deposit_diary")
    parser.add_argument("--json", action="store_true", help="Вывести собранный dict как JSON")
    parser.add_argument("--no-write", action="store_true", help="Не писать в state.json")
    args = parser.parse_args()

    load_dotenv(dotenv_path=ROOT / ".env")
    token = (os.getenv("TELEGRAM_TOKEN") or "").strip()
    channel_id = (os.getenv("CHANNEL_ID") or "").strip()

    if not token or not channel_id:
        print("TELEGRAM_TOKEN или CHANNEL_ID пустые", file=sys.stderr)
        return 1

    stats = asyncio.run(_collect_stats(token, channel_id))

    if not args.no_write:
        append_channel_stats(STATE_PATH, stats)

    title = _fmt(stats.get("channel_title"), "n/a")
    subs = _fmt(stats.get("subscribers_count"))
    can_post = _fmt(stats.get("bot_can_post"))
    post7 = stats.get("posts_last_7d", 0)
    post30 = stats.get("posts_last_30d", 0)
    pd = stats.get("pending_drafts", {"news": 0, "author_notes": 0, "weekly_diary": 0})
    trades = stats.get("active_confirm_trades", 0)

    print("=== CHANNEL STATS ===")
    print(f"  channel:           {title} (@{channel_id.lstrip('@')})")
    print(f"  subscribers:       {subs}")
    print(f"  bot can post:      {can_post}")
    print(f"  posts last 7d:     {post7}")
    print(f"  posts last 30d:    {post30}")
    print(f"  pending drafts:    news={pd['news']} / author_notes={pd['author_notes']} / weekly_diary={pd['weekly_diary']}")
    print(f"  active trades:     {trades}")
    if args.no_write:
        print("  written to:        (skipped --no-write)")
    else:
        print(f"  written to:        state.json.channel_stats_log")

    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())