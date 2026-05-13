"""Tests for core/trade_state.py."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.trade_state import (
    get_gate_screenshot,
    get_trade_channel_posts_today,
    increment_trade_channel_posts_today,
    set_gate_screenshot,
    set_last_trade_scan_at,
    set_last_trade_tick_at,
    today_utc_iso,
)


_NOW = datetime(2026, 5, 14, 15, 30, tzinfo=timezone.utc)


# ---------- today_utc_iso ----------


def test_today_utc_iso_default_format():
    result = today_utc_iso(_NOW)
    assert result == "2026-05-14"


def test_today_utc_iso_uses_real_time_when_no_arg():
    result = today_utc_iso()
    # Просто проверим формат, не значение
    assert len(result) == 10
    assert result.count("-") == 2


# ---------- get_trade_channel_posts_today ----------


def test_get_posts_today_fresh_date_returns_count():
    state = {
        "trade_channel_posts_date": "2026-05-14",
        "trade_channel_posts_today": 3,
    }
    assert get_trade_channel_posts_today(state, now=_NOW) == 3


def test_get_posts_today_stale_date_returns_zero():
    """Если дата в state не сегодня — счётчик протух."""
    state = {
        "trade_channel_posts_date": "2026-05-13",
        "trade_channel_posts_today": 10,
    }
    assert get_trade_channel_posts_today(state, now=_NOW) == 0


def test_get_posts_today_missing_date_returns_zero():
    state = {"trade_channel_posts_today": 5}  # no date
    assert get_trade_channel_posts_today(state, now=_NOW) == 0


def test_get_posts_today_invalid_count_returns_zero():
    state = {
        "trade_channel_posts_date": "2026-05-14",
        "trade_channel_posts_today": "not a number",
    }
    assert get_trade_channel_posts_today(state, now=_NOW) == 0


def test_get_posts_today_none_count_returns_zero():
    state = {
        "trade_channel_posts_date": "2026-05-14",
        "trade_channel_posts_today": None,
    }
    assert get_trade_channel_posts_today(state, now=_NOW) == 0


# ---------- increment_trade_channel_posts_today ----------


def test_increment_on_fresh_state_starts_at_one():
    state = {}
    increment_trade_channel_posts_today(state, now=_NOW)
    assert state["trade_channel_posts_today"] == 1
    assert state["trade_channel_posts_date"] == "2026-05-14"


def test_increment_same_day_adds_one():
    state = {
        "trade_channel_posts_date": "2026-05-14",
        "trade_channel_posts_today": 5,
    }
    increment_trade_channel_posts_today(state, now=_NOW)
    assert state["trade_channel_posts_today"] == 6


def test_increment_resets_when_date_changed():
    state = {
        "trade_channel_posts_date": "2026-05-13",
        "trade_channel_posts_today": 10,
    }
    increment_trade_channel_posts_today(state, now=_NOW)
    assert state["trade_channel_posts_today"] == 1
    assert state["trade_channel_posts_date"] == "2026-05-14"


def test_increment_with_invalid_existing_counter():
    state = {
        "trade_channel_posts_date": "2026-05-14",
        "trade_channel_posts_today": "garbage",
    }
    increment_trade_channel_posts_today(state, now=_NOW)
    assert state["trade_channel_posts_today"] == 1


# ---------- set_last_trade_scan_at / tick_at ----------


def test_set_last_scan_at_writes_to_state():
    state = {}
    set_last_trade_scan_at(state, "2026-05-14T10:00:00+00:00")
    assert state["last_trade_scan_at"] == "2026-05-14T10:00:00+00:00"


def test_set_last_tick_at_writes_to_state():
    state = {}
    set_last_trade_tick_at(state, "2026-05-14T11:00:00+00:00")
    assert state["last_trade_tick_at"] == "2026-05-14T11:00:00+00:00"


# ---------- gate_screenshot ----------


def test_set_gate_screenshot_creates_mapping():
    state = {}
    set_gate_screenshot(state, "t1", "/tmp/x.png")
    assert state["gate_screenshots"] == {"t1": "/tmp/x.png"}


def test_set_gate_screenshot_preserves_existing():
    state = {"gate_screenshots": {"t0": "/old.png"}}
    set_gate_screenshot(state, "t1", "/new.png")
    assert state["gate_screenshots"] == {"t0": "/old.png", "t1": "/new.png"}


def test_set_gate_screenshot_overrides_same_trade_id():
    state = {"gate_screenshots": {"t1": "/old.png"}}
    set_gate_screenshot(state, "t1", "/new.png")
    assert state["gate_screenshots"] == {"t1": "/new.png"}


def test_set_gate_screenshot_empty_trade_id_is_noop():
    state = {}
    set_gate_screenshot(state, "", "/tmp/x.png")
    assert "gate_screenshots" not in state


def test_set_gate_screenshot_repairs_non_dict():
    """Если поле gate_screenshots — не dict (corrupted), исправляем."""
    state = {"gate_screenshots": "garbage"}
    set_gate_screenshot(state, "t1", "/x.png")
    assert state["gate_screenshots"] == {"t1": "/x.png"}


def test_get_gate_screenshot_returns_path():
    state = {"gate_screenshots": {"t1": "/tmp/x.png"}}
    assert get_gate_screenshot(state, "t1") == "/tmp/x.png"


def test_get_gate_screenshot_missing_returns_none():
    state = {"gate_screenshots": {"t1": "/x.png"}}
    assert get_gate_screenshot(state, "missing") is None


def test_get_gate_screenshot_empty_trade_id_returns_none():
    state = {"gate_screenshots": {"t1": "/x.png"}}
    assert get_gate_screenshot(state, "") is None


def test_get_gate_screenshot_no_field_returns_none():
    assert get_gate_screenshot({}, "t1") is None


def test_get_gate_screenshot_non_dict_field_returns_none():
    state = {"gate_screenshots": "garbage"}
    assert get_gate_screenshot(state, "t1") is None
