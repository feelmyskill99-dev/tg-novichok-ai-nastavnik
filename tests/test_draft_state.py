"""Tests for core/draft_state.py."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.draft_state import (
    get_author_notes_week_count,
    get_awaiting_edit,
    get_news_post_counter,
    increment_author_notes_week_count,
    increment_news_post_counter,
    set_awaiting_edit,
)


_MAY_14_2026 = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)


# ---------- awaiting_*_edit ----------


def test_get_awaiting_edit_empty_returns_empty_string():
    assert get_awaiting_edit({}, "news") == ""
    assert get_awaiting_edit({}, "author") == ""


def test_get_awaiting_edit_returns_existing_draft_id():
    state = {"awaiting_news_edit_for": "d1"}
    assert get_awaiting_edit(state, "news") == "d1"


def test_get_awaiting_edit_different_kinds_independent():
    state = {
        "awaiting_news_edit_for": "n1",
        "awaiting_author_edit_for": "a1",
    }
    assert get_awaiting_edit(state, "news") == "n1"
    assert get_awaiting_edit(state, "author") == "a1"


def test_set_awaiting_edit_writes_key():
    state = {}
    set_awaiting_edit(state, "news", "d1")
    assert state["awaiting_news_edit_for"] == "d1"


def test_set_awaiting_edit_with_none_removes_key():
    state = {"awaiting_news_edit_for": "d1"}
    set_awaiting_edit(state, "news", None)
    assert "awaiting_news_edit_for" not in state


def test_set_awaiting_edit_with_empty_string_removes_key():
    state = {"awaiting_news_edit_for": "d1"}
    set_awaiting_edit(state, "news", "")
    assert "awaiting_news_edit_for" not in state


def test_set_awaiting_edit_only_affects_specified_kind():
    state = {"awaiting_news_edit_for": "n1", "awaiting_author_edit_for": "a1"}
    set_awaiting_edit(state, "news", None)
    assert "awaiting_news_edit_for" not in state
    assert state["awaiting_author_edit_for"] == "a1"  # не тронут


def test_get_awaiting_edit_non_string_value_coerced():
    state = {"awaiting_news_edit_for": 42}
    assert get_awaiting_edit(state, "news") == "42"


# ---------- news_post_counter ----------


def test_get_news_counter_empty_state():
    assert get_news_post_counter({}) == 0


def test_get_news_counter_existing():
    state = {"news_post_counter": 5}
    assert get_news_post_counter(state) == 5


def test_get_news_counter_invalid_returns_zero():
    state = {"news_post_counter": "not a number"}
    assert get_news_post_counter(state) == 0


def test_get_news_counter_none_returns_zero():
    state = {"news_post_counter": None}
    assert get_news_post_counter(state) == 0


def test_increment_news_counter_from_zero_returns_one():
    state = {}
    assert increment_news_post_counter(state) == 1
    assert state["news_post_counter"] == 1


def test_increment_news_counter_returns_new_value():
    state = {"news_post_counter": 7}
    result = increment_news_post_counter(state)
    assert result == 8
    assert state["news_post_counter"] == 8


def test_increment_news_counter_recovers_from_garbage():
    state = {"news_post_counter": "garbage"}
    result = increment_news_post_counter(state)
    assert result == 1


# ---------- author_notes_week_count ----------


def test_get_author_week_count_empty_state():
    assert get_author_notes_week_count({}, now=_MAY_14_2026) == 0


def test_get_author_week_count_fresh_key():
    """2026-05-14 — ISO week 20 of 2026."""
    state = {
        "author_notes_week_key": "2026-20",
        "author_notes_week_count": 3,
    }
    assert get_author_notes_week_count(state, now=_MAY_14_2026) == 3


def test_get_author_week_count_stale_key_returns_zero():
    state = {
        "author_notes_week_key": "2026-15",  # старая неделя
        "author_notes_week_count": 99,
    }
    assert get_author_notes_week_count(state, now=_MAY_14_2026) == 0


def test_get_author_week_count_invalid_returns_zero():
    state = {
        "author_notes_week_key": "2026-20",
        "author_notes_week_count": "garbage",
    }
    assert get_author_notes_week_count(state, now=_MAY_14_2026) == 0


def test_increment_author_week_fresh_state_sets_one():
    state = {}
    increment_author_notes_week_count(state, now=_MAY_14_2026)
    assert state["author_notes_week_count"] == 1
    assert state["author_notes_week_key"] == "2026-20"
    assert "last_author_note_at" in state


def test_increment_author_week_same_week_adds_one():
    state = {
        "author_notes_week_key": "2026-20",
        "author_notes_week_count": 5,
    }
    increment_author_notes_week_count(state, now=_MAY_14_2026)
    assert state["author_notes_week_count"] == 6
    assert state["author_notes_week_key"] == "2026-20"


def test_increment_author_week_new_week_resets_to_one():
    state = {
        "author_notes_week_key": "2026-19",  # прошлая неделя
        "author_notes_week_count": 99,
    }
    increment_author_notes_week_count(state, now=_MAY_14_2026)
    assert state["author_notes_week_count"] == 1
    assert state["author_notes_week_key"] == "2026-20"


def test_increment_author_week_recovers_from_garbage_count():
    state = {
        "author_notes_week_key": "2026-20",
        "author_notes_week_count": "garbage",
    }
    increment_author_notes_week_count(state, now=_MAY_14_2026)
    assert state["author_notes_week_count"] == 1


def test_increment_author_week_writes_iso_timestamp():
    state = {}
    increment_author_notes_week_count(state, now=_MAY_14_2026)
    # Должно парситься как ISO
    parsed = datetime.fromisoformat(state["last_author_note_at"])
    assert parsed.tzinfo is not None
