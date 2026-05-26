"""Tests for core.content_mix_writer.append_channel_stats. rebranding stage 3."""
from __future__ import annotations

import json

from core.content_mix_writer import append_channel_stats
from core.json_store import load_json


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
