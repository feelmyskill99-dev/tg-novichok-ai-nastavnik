import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.content_mix_writer import (
    migrate_state, make_event, prune_log, append_event,
)

_NOW = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)


def _ev_at(category: str, days_ago: float, *, published_to: str = "channel") -> dict:
    ts = (_NOW - timedelta(days=days_ago)).isoformat(timespec="seconds")
    return {
        "timestamp": ts,
        "post_type": category,
        "category": category,
        "published_to": published_to,
        "title": "",
        "source": "test",
    }


class TestMigrateState:
    def test_migrate_when_content_mix_log_is_not_list_no_change(self):
        # Текущий контракт: если content_mix_log есть (даже non-list) и
        # legacy posts_log нет — migrate ничего не делает (return False).
        # Это безопасно: append_event позже заменит на пустой список.
        state = {"content_mix_log": "garbage"}
        result = migrate_state(state)
        assert result is False
        # state["content_mix_log"] остаётся "garbage" (caller вызовет append_event)
        assert state["content_mix_log"] == "garbage"

    def test_migrate_legacy_posts_log_with_full_schema(self):
        state = {"posts_log": [{"type": "market", "ts": "2026-05-01T10:00:00+00:00"}]}
        migrate_state(state)
        assert len(state["content_mix_log"]) == 1
        ev = state["content_mix_log"][0]
        expected_keys = {"timestamp", "post_type", "category", "published_to", "title", "source"}
        assert set(ev.keys()) == expected_keys
        assert ev["timestamp"] == "2026-05-01T10:00:00+00:00"
        assert ev["post_type"] == "market"
        assert ev["category"] == "market_chart"
        assert ev["published_to"] == "channel"
        assert ev["title"] == ""
        assert ev["source"] == "legacy"

    def test_migrate_legacy_preserves_existing_timestamp(self):
        state = {"posts_log": [{"type": "news", "ts": "2026-04-15T08:00:00+00:00"}]}
        migrate_state(state)
        assert state["content_mix_log"][0]["timestamp"] == "2026-04-15T08:00:00+00:00"

    def test_migrate_legacy_unknown_type_becomes_other_category(self):
        state = {"posts_log": [{"type": "weird_unknown_xyz", "ts": "2026-05-01T00:00:00+00:00"}]}
        migrate_state(state)
        assert state["content_mix_log"][0]["category"] == "other"

    def test_migrate_empty_legacy_list_creates_empty_log(self):
        state = {"posts_log": []}
        migrate_state(state)
        assert state["content_mix_log"] == []
        assert state.get("posts_log") == []


class TestMakeEvent:
    def test_make_event_title_exactly_240(self):
        title = "a" * 240
        ev = make_event("news", published_to="channel", title=title, now=_NOW)
        assert len(ev["title"]) == 240

    def test_make_event_title_241_truncated_to_240(self):
        title = "a" * 241
        ev = make_event("news", published_to="channel", title=title, now=_NOW)
        assert len(ev["title"]) == 240

    def test_make_event_with_unicode_title(self):
        title = "Привет мир 🌍"
        ev = make_event("news", published_to="channel", title=title, now=_NOW)
        assert ev["title"] == title

    def test_make_event_with_none_title_returns_empty_string(self):
        ev = make_event("news", published_to="owner", title=None, now=_NOW)
        assert ev["title"] == ""

    def test_make_event_explicit_now_used(self):
        future = datetime(2030, 1, 1, 0, 0, tzinfo=timezone.utc)
        ev = make_event("news", published_to="channel", now=future)
        assert ev["timestamp"].startswith("2030-01-01")


class TestPruneLog:
    def test_prune_log_thousand_events_capped(self):
        # 1000 событий за последние 5 дней (все попадают в window=14).
        # После cap=500 — остаются 500 последних.
        events = [
            _ev_at("market", days_ago=i / 200.0)  # 0.0 - 5.0 days
            for i in range(1000)
        ]
        pruned = prune_log(events, now=_NOW, days=14, cap=500)
        assert len(pruned) == 500

    def test_prune_log_zero_days_keeps_only_events_at_now(self):
        # days=0 → cutoff=now → ts >= now → проходит только days_ago=0.
        events = [_ev_at("news", days_ago=i) for i in range(5)]
        pruned = prune_log(events, now=_NOW, days=0)
        # days_ago=0 → ts ровно now → попадает в окно
        assert len(pruned) == 1

    def test_prune_log_negative_cap_python_slice_semantics(self):
        # fresh[-cap:] с cap=-1 → fresh[1:] = всё кроме первого.
        # Это не идеальное поведение, но это контракт текущей реализации.
        events = [_ev_at("education", days_ago=1) for _ in range(10)]
        pruned = prune_log(events, cap=-1, now=_NOW)
        assert len(pruned) == 9

    def test_prune_log_preserves_event_order(self):
        timestamps = [_NOW - timedelta(days=i) for i in [3, 2, 1]]
        events = [{"timestamp": ts.isoformat(timespec="seconds"), "post_type": "news", "category": "news", "published_to": "channel"} for ts in timestamps]
        pruned = prune_log(events, now=_NOW, days=10, cap=100)
        assert [ev["timestamp"] for ev in pruned] == [ts.isoformat(timespec="seconds") for ts in timestamps]


class TestAppendEvent:
    def test_append_event_to_state_with_non_list_log(self):
        state = {"content_mix_log": "garbage"}
        ev = _ev_at("news", days_ago=0)
        append_event(state, ev, now=_NOW)
        assert isinstance(state["content_mix_log"], list)
        assert len(state["content_mix_log"]) == 1

    def test_append_event_does_not_mutate_other_state_keys(self):
        state = {"unrelated": "preserved", "other": [1, 2]}
        ev = _ev_at("news", days_ago=0)
        append_event(state, ev, now=_NOW)
        assert state["unrelated"] == "preserved"
        assert state["other"] == [1, 2]

    def test_append_event_with_custom_cap(self):
        old_events = [_ev_at("news", days_ago=1)] * 10
        state = {"content_mix_log": old_events}
        ev = _ev_at("news", days_ago=0)
        append_event(state, ev, cap=3, now=_NOW)
        assert len(state["content_mix_log"]) == 3

    def test_append_event_with_custom_days_window(self):
        state = {
            "content_mix_log": [
                _ev_at("news", days_ago=5),
                _ev_at("news", days_ago=20),
            ]
        }
        ev = _ev_at("news", days_ago=0)
        append_event(state, ev, days=7, now=_NOW)
        assert len(state["content_mix_log"]) == 2

    def test_append_event_preserves_new_event_in_result(self):
        state = {"content_mix_log": [_ev_at("news", days_ago=100)]}
        new_ev = _ev_at("market", days_ago=0)
        append_event(state, new_ev, days=1, now=_NOW)
        assert len(state["content_mix_log"]) == 1
        assert state["content_mix_log"][0] == new_ev


class TestCombined:
    def test_full_cycle_migrate_then_append(self):
        state = {"posts_log": [{"type": "market", "ts": "2026-05-01T00:00:00+00:00"}]}
        new_ev = make_event("news", published_to="channel", now=_NOW)
        append_event(state, new_ev, now=_NOW)
        assert "posts_log" not in state
        assert len(state["content_mix_log"]) == 2
        assert state["content_mix_log"][0]["timestamp"] == "2026-05-01T00:00:00+00:00"
        assert state["content_mix_log"][1] == new_ev

    def test_append_event_multiple_times_in_sequence(self):
        state = {"content_mix_log": []}
        for typ in ["market_chart", "education", "news", "author_note", "trade_diary"]:
            ev = make_event(typ, published_to="channel", now=_NOW)
            append_event(state, ev, now=_NOW)
        assert len(state["content_mix_log"]) == 5
        types = [ev["post_type"] for ev in state["content_mix_log"]]
        assert set(types) == {"market_chart", "education", "news", "author_note", "trade_diary"}