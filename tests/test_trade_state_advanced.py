import sys
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.trade_state import (
    today_utc_iso,
    get_trade_channel_posts_today,
    increment_trade_channel_posts_today,
    set_last_trade_scan_at,
    set_last_trade_tick_at,
    set_gate_screenshot,
    get_gate_screenshot,
    remember_trade_message,
    lookup_trade_by_message,
)

_NOW = datetime(2026, 5, 14, 12, 0, 0, tzinfo=timezone.utc)
_DAY1_NOON = datetime(2026, 5, 14, 12, 0, 0, tzinfo=timezone.utc)
_DAY2_NOON = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)


class TestTodayUtcIsoBoundary:
    def test_today_utc_iso_at_midnight_utc(self):
        now = datetime(2026, 5, 14, 0, 0, 0, tzinfo=timezone.utc)
        assert today_utc_iso(now) == "2026-05-14"

    def test_today_utc_iso_just_before_midnight(self):
        now = datetime(2026, 5, 14, 23, 59, 59, tzinfo=timezone.utc)
        assert today_utc_iso(now) == "2026-05-14"

    def test_today_utc_iso_first_day_of_year(self):
        now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
        assert today_utc_iso(now) == "2026-01-01"


class TestIncrementSequence:
    def test_increment_sequence_same_day(self):
        state = {}
        for _ in range(10):
            increment_trade_channel_posts_today(state, now=_NOW)
        assert state["trade_channel_posts_today"] == 10

    def test_increment_across_day_boundary(self):
        state = {}
        for _ in range(5):
            increment_trade_channel_posts_today(state, now=_DAY1_NOON)
        assert state["trade_channel_posts_today"] == 5
        increment_trade_channel_posts_today(state, now=_DAY2_NOON)
        assert state["trade_channel_posts_today"] == 1
        assert state["trade_channel_posts_date"] == "2026-05-15"

    def test_get_after_increment_returns_same_value(self):
        state = {}
        for _ in range(3):
            increment_trade_channel_posts_today(state, now=_NOW)
        assert get_trade_channel_posts_today(state, now=_NOW) == 3


class TestSetLastOverwrite:
    def test_set_last_scan_at_overwrites_existing(self):
        state = {"last_trade_scan_at": "old"}
        set_last_trade_scan_at(state, "new")
        assert state["last_trade_scan_at"] == "new"

    def test_set_last_scan_at_preserves_other_keys(self):
        state = {"foo": "bar"}
        set_last_trade_scan_at(state, "new")
        assert state["foo"] == "bar"


class TestGateScreenshotSequence:
    def test_multiple_set_gate_screenshot_accumulates(self):
        state = {}
        set_gate_screenshot(state, "t1", "/p1.png")
        set_gate_screenshot(state, "t2", "/p2.png")
        set_gate_screenshot(state, "t3", "/p3.png")
        assert len(state["gate_screenshots"]) == 3

    def test_set_gate_screenshot_with_unicode_path(self):
        state = {}
        path = "D:/Вайбкодинг/screenshot.png"
        set_gate_screenshot(state, "t1", path)
        assert get_gate_screenshot(state, "t1") == path

    def test_get_gate_screenshot_with_falsy_value_in_map(self):
        state = {"gate_screenshots": {"t1": ""}}
        result = get_gate_screenshot(state, "t1")
        assert result == ""          # not None


class TestTradeMessageIndexSequence:
    def test_remember_message_then_lookup_round_trip(self):
        state = {}
        remember_trade_message(state, 42, "t1")
        assert lookup_trade_by_message(state, 42) == "t1"

    def test_remember_message_id_str_lookup_works(self):
        state = {}
        remember_trade_message(state, 42, "t1")
        # both access methods yield same result
        assert lookup_trade_by_message(state, 42) == "t1"
        assert state["trade_message_index"]["42"] == "t1"

    def test_remember_cap_keeps_most_recent(self):
        state = {}
        for i in range(100, 110):
            remember_trade_message(state, i, str(i), cap=5)
        idx = state["trade_message_index"]
        assert len(idx) == 5
        for key in [str(k) for k in range(105, 110)]:
            assert key in idx
        for key in [str(k) for k in range(100, 105)]:
            assert key not in idx

    def test_lookup_after_overwrite_returns_new_trade_id(self):
        state = {}
        remember_trade_message(state, 42, "old")
        remember_trade_message(state, 42, "new")
        assert lookup_trade_by_message(state, 42) == "new"

    def test_remember_with_cap_one(self):
        state = {}
        for i in range(1, 4):
            remember_trade_message(state, i, f"t{i}", cap=1)
        idx = state["trade_message_index"]
        assert len(idx) == 1
        assert idx["3"] == "t3"

    def test_remember_with_negative_message_id_is_noop(self):
        state = {}
        remember_trade_message(state, -42, "t1")
        # function should not raise, and lookup should work
        result = lookup_trade_by_message(state, -42)
        assert result == "t1"


class TestCombinedScenarios:
    def test_full_trade_state_workflow(self):
        state = {}
        for _ in range(3):
            increment_trade_channel_posts_today(state, now=_NOW)
        set_last_trade_scan_at(state, "2026-05-14T10:00")
        remember_trade_message(state, 42, "t1")
        remember_trade_message(state, 43, "t2")
        set_gate_screenshot(state, "t1", "/tmp/s1.png")
        assert state["trade_channel_posts_today"] == 3
        assert state["last_trade_scan_at"] == "2026-05-14T10:00"
        assert lookup_trade_by_message(state, 42) == "t1"
        assert lookup_trade_by_message(state, 43) == "t2"
        assert get_gate_screenshot(state, "t1") == "/tmp/s1.png"

    def test_independent_state_dicts_dont_share(self):
        state1 = {}
        state2 = {}
        increment_trade_channel_posts_today(state1, now=_NOW)
        assert "trade_channel_posts_today" in state1
        assert "trade_channel_posts_today" not in state2

    def test_state_dict_can_be_serialized_to_json(self):
        state = {}
        for _ in range(3):
            increment_trade_channel_posts_today(state, now=_NOW)
        set_last_trade_scan_at(state, "2026-05-14T10:00")
        remember_trade_message(state, 42, "t1")
        set_gate_screenshot(state, "t1", "/tmp/s1.png")
        json.dumps(state)  # should not raise