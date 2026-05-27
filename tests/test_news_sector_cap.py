"""Stage 14b — sector cap в один день.

Защита от перекоса (27.04: 4 stablecoin-поста подряд за час).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from news.deduplicator import NewsDeduplicator


def _make_record(sector: str, *, hours_ago: float = 0.0, decision: str = "published_channel") -> dict:
    ts = datetime.now(tz=timezone.utc) - timedelta(hours=hours_ago)
    return {
        "title_hash": f"hash-{sector}-{hours_ago}",
        "title": f"Sample news in {sector}",
        "url": f"https://example/{sector}",
        "source": "test",
        "posted_at": ts.isoformat(timespec="seconds"),
        "impact_score": 80,
        "sector": sector,
        "decision": decision,
        "short_summary": "",
    }


def test_posted_today_in_sector_counts_only_target_sector(tmp_path: Path):
    history = tmp_path / "news_history.json"
    records = [
        _make_record("stablecoins", hours_ago=0.5),
        _make_record("stablecoins", hours_ago=1.0),
        _make_record("ai_crypto", hours_ago=2.0),
    ]
    history.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    dedup = NewsDeduplicator(history)
    assert dedup.posted_today_in_sector("stablecoins") == 2
    assert dedup.posted_today_in_sector("ai_crypto") == 1
    assert dedup.posted_today_in_sector("unknown_sector") == 0


def test_posted_today_in_sector_ignores_other_days(tmp_path: Path):
    history = tmp_path / "news_history.json"
    records = [
        _make_record("stablecoins", hours_ago=0.5),
        _make_record("stablecoins", hours_ago=30),  # вчера
        _make_record("stablecoins", hours_ago=50),  # позавчера
    ]
    history.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    dedup = NewsDeduplicator(history)
    assert dedup.posted_today_in_sector("stablecoins") == 1


def test_posted_today_in_sector_only_channel_filter(tmp_path: Path):
    history = tmp_path / "news_history.json"
    records = [
        _make_record("stablecoins", hours_ago=0.5, decision="published_channel"),
        _make_record("stablecoins", hours_ago=1.0, decision="sent_owner"),
        _make_record("stablecoins", hours_ago=1.5, decision="skipped"),
        _make_record("stablecoins", hours_ago=2.0, decision="claude_rejected"),
    ]
    history.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    dedup = NewsDeduplicator(history)
    # default: считает published + sent_owner, исключает skipped/claude_rejected
    assert dedup.posted_today_in_sector("stablecoins") == 2
    # only_channel: только published
    assert dedup.posted_today_in_sector("stablecoins", only_channel=True) == 1


def test_posted_today_in_sector_empty_sector_returns_zero(tmp_path: Path):
    history = tmp_path / "news_history.json"
    history.write_text("[]", encoding="utf-8")
    dedup = NewsDeduplicator(history)
    assert dedup.posted_today_in_sector("") == 0


def test_posted_today_in_sector_missing_file(tmp_path: Path):
    history = tmp_path / "does_not_exist.json"
    dedup = NewsDeduplicator(history)
    assert dedup.posted_today_in_sector("stablecoins") == 0
