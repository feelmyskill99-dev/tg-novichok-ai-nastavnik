"""Tests for core/content_mix_writer.py."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.content_mix_writer import (
    append_event,
    make_event,
    migrate_state,
    prune_log,
)


_NOW = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)


# ---------- migrate_state ----------


def test_migrate_state_noop_when_content_mix_log_present():
    state = {"content_mix_log": [{"timestamp": "x"}]}
    changed = migrate_state(state)
    assert changed is False
    assert state["content_mix_log"] == [{"timestamp": "x"}]


def test_migrate_state_creates_empty_log_when_missing():
    state = {}
    changed = migrate_state(state)
    assert changed is True
    assert state["content_mix_log"] == []


def test_migrate_state_from_legacy_posts_log():
    state = {
        "posts_log": [
            {"type": "market", "ts": "2026-05-01T10:00:00+00:00"},
            {"type": "news", "ts": "2026-05-02T10:00:00+00:00"},
        ],
    }
    changed = migrate_state(state)
    assert changed is True
    assert "posts_log" not in state
    assert len(state["content_mix_log"]) == 2
    assert state["content_mix_log"][0]["post_type"] == "market"
    assert state["content_mix_log"][0]["category"] == "market_chart"
    assert state["content_mix_log"][0]["published_to"] == "channel"
    assert state["content_mix_log"][0]["source"] == "legacy"


def test_migrate_state_legacy_skips_non_dict_entries():
    state = {"posts_log": [{"type": "market", "ts": "2026-05-01T10:00:00+00:00"}, "garbage", 42]}
    migrate_state(state)
    assert len(state["content_mix_log"]) == 1


def test_migrate_state_legacy_missing_ts_uses_now():
    state = {"posts_log": [{"type": "market"}]}
    migrate_state(state)
    assert state["content_mix_log"][0]["timestamp"]  # not empty


# ---------- make_event ----------


def test_make_event_basic():
    ev = make_event("market", published_to="channel", title="t", source="manual", now=_NOW)
    assert ev["post_type"] == "market"
    assert ev["category"] == "market_chart"
    assert ev["published_to"] == "channel"
    assert ev["title"] == "t"
    assert ev["source"] == "manual"
    assert ev["timestamp"].startswith("2026-05-14")


def test_make_event_title_truncated_to_240():
    long_title = "x" * 500
    ev = make_event("news", published_to="owner", title=long_title, now=_NOW)
    assert len(ev["title"]) == 240


def test_make_event_empty_post_type_yields_other_category():
    ev = make_event("", published_to="channel", now=_NOW)
    assert ev["category"] == "other"


def test_make_event_now_defaults_to_real_time():
    ev = make_event("news", published_to="owner")
    # Парсится как ISO
    datetime.fromisoformat(ev["timestamp"])


# ---------- prune_log ----------


def test_prune_log_empty_input():
    assert prune_log([]) == []


def test_prune_log_drops_old_events():
    events = [
        {"timestamp": (_NOW - timedelta(days=30)).isoformat(timespec="seconds")},
        {"timestamp": (_NOW - timedelta(days=5)).isoformat(timespec="seconds")},
        {"timestamp": (_NOW - timedelta(days=1)).isoformat(timespec="seconds")},
    ]
    result = prune_log(events, now=_NOW, days=14)
    assert len(result) == 2


def test_prune_log_caps_size():
    events = [
        {"timestamp": (_NOW - timedelta(hours=i)).isoformat(timespec="seconds")}
        for i in range(20)
    ]
    result = prune_log(events, now=_NOW, days=14, cap=5)
    assert len(result) == 5


def test_prune_log_skips_invalid_timestamps():
    events = [
        {"timestamp": "garbage"},
        {"timestamp": ""},
        {},  # missing timestamp key
        {"timestamp": (_NOW - timedelta(hours=1)).isoformat(timespec="seconds")},
    ]
    result = prune_log(events, now=_NOW)
    assert len(result) == 1


def test_prune_log_handles_naive_datetime_as_utc():
    events = [
        {"timestamp": (_NOW - timedelta(hours=1)).replace(tzinfo=None).isoformat()},
    ]
    result = prune_log(events, now=_NOW, days=14)
    assert len(result) == 1


def test_prune_log_skips_non_dict_entries():
    events = [
        "garbage",
        42,
        {"timestamp": (_NOW - timedelta(hours=1)).isoformat()},
    ]
    result = prune_log(events, now=_NOW)
    assert len(result) == 1


def test_prune_log_non_list_returns_empty():
    assert prune_log("not a list") == []
    assert prune_log(None) == []


# ---------- append_event ----------


def test_append_event_to_empty_state():
    state = {}
    ev = make_event("market", published_to="channel", now=_NOW)
    append_event(state, ev, now=_NOW)
    assert len(state["content_mix_log"]) == 1


def test_append_event_migrates_legacy():
    state = {"posts_log": [{"type": "news", "ts": "2026-05-01T00:00:00+00:00"}]}
    ev = make_event("market", published_to="channel", now=_NOW)
    append_event(state, ev, now=_NOW)
    assert "posts_log" not in state
    # legacy запись + новая = 2
    assert len(state["content_mix_log"]) == 2


def test_append_event_respects_cap():
    state = {"content_mix_log": [
        {"timestamp": (_NOW - timedelta(hours=i)).isoformat()}
        for i in range(100)
    ]}
    for _ in range(10):
        append_event(state, make_event("news", published_to="channel", now=_NOW),
                     now=_NOW, cap=20)
    assert len(state["content_mix_log"]) == 20


def test_append_event_drops_events_older_than_window():
    state = {"content_mix_log": [
        {"timestamp": (_NOW - timedelta(days=30)).isoformat()},
    ]}
    append_event(state, make_event("market", published_to="channel", now=_NOW), now=_NOW)
    # Старая запись (30 дней) выкинута, осталась только новая
    assert len(state["content_mix_log"]) == 1
    assert state["content_mix_log"][0]["post_type"] == "market"
