"""Tests for core.content_mix_writer.append_channel_stats. rebranding stage 3.

Также: tests for scripts.channel_stats.count_pending — баг-фикс 2026-05-26
где `len(drafts_file)` ошибочно возвращал total вместо pending-only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.content_mix_writer import append_channel_stats
from core.json_store import load_json
from scripts.channel_stats import count_pending, PENDING_STATUSES


def test_append_channel_stats_adds_entry(tmp_path):
    state_file = tmp_path / "state.json"
    append_channel_stats(state_file, {"subscribers_count": 10})

    data = load_json(state_file, default={}, expected_type=dict)
    assert "channel_stats_log" in data
    assert len(data["channel_stats_log"]) == 1
    entry = data["channel_stats_log"][0]
    assert entry["subscribers_count"] == 10
    assert "recorded_at" in entry


def test_append_channel_stats_preserves_caller_recorded_at(tmp_path):
    state_file = tmp_path / "state.json"
    append_channel_stats(state_file, {
        "subscribers_count": 5,
        "recorded_at": "2026-05-26T12:00:00+00:00",
    })
    data = load_json(state_file, default={}, expected_type=dict)
    assert data["channel_stats_log"][0]["recorded_at"] == "2026-05-26T12:00:00+00:00"


def test_append_channel_stats_caps_at_max_entries(tmp_path):
    state_file = tmp_path / "state.json"
    for i in range(5):
        append_channel_stats(state_file, {"subscribers_count": i}, max_entries=3)

    data = load_json(state_file, default={}, expected_type=dict)
    log = data["channel_stats_log"]
    assert len(log) == 3
    # последние 3 (2, 3, 4) — старые (0, 1) обрезаны
    assert [e["subscribers_count"] for e in log] == [2, 3, 4]


def test_append_channel_stats_preserves_other_state_keys(tmp_path):
    state_file = tmp_path / "state.json"
    # preset state with other fields
    state_file.write_text(
        json.dumps({"some_other_key": "value", "counter": 42}),
        encoding="utf-8",
    )
    append_channel_stats(state_file, {"subscribers_count": 1})

    data = load_json(state_file, default={}, expected_type=dict)
    assert data["some_other_key"] == "value"
    assert data["counter"] == 42
    assert len(data["channel_stats_log"]) == 1


# ============================================================
# count_pending — fix bug from 2026-05-26
# ============================================================


def test_count_pending_counts_only_pending_review_and_revised():
    drafts = [
        {"status": "pending_review"},
        {"status": "revised"},
        {"status": "published"},
        {"status": "rejected"},
        {"status": "approved"},
        {"status": "pending_review"},
    ]
    # 2 pending_review + 1 revised
    assert count_pending(drafts) == 3


def test_count_pending_empty_list():
    assert count_pending([]) == 0


def test_count_pending_handles_non_list():
    assert count_pending(None) == 0
    assert count_pending({}) == 0
    assert count_pending("not a list") == 0
    assert count_pending(42) == 0


def test_count_pending_skips_non_dict_items():
    drafts = [
        {"status": "pending_review"},
        "broken",
        None,
        42,
        {"status": "revised"},
    ]
    assert count_pending(drafts) == 2


def test_count_pending_skips_items_without_status():
    drafts = [
        {"status": "pending_review"},
        {"draft_id": "x"},   # нет status
        {},                  # пустой dict
        {"status": None},    # status явно None
    ]
    assert count_pending(drafts) == 1


def test_pending_statuses_constant_includes_both_states():
    """PENDING_STATUSES — публичная константа; должна оставаться стабильной."""
    assert "pending_review" in PENDING_STATUSES
    assert "revised" in PENDING_STATUSES
    # published/rejected/approved НЕ должны быть в pending
    assert "published" not in PENDING_STATUSES
    assert "rejected" not in PENDING_STATUSES
