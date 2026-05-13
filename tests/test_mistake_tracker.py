import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.mistake_tracker import MistakeTracker

# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

THEMES = {
    "fomo": {"title": "FOMO трейдинг"},
    "no_stop": {"title": "Торговля без стопа"},
    "overleverage": {"title": "Слишком большое плечо"},
}


def make_themes(tmp_path, data=None):
    path = tmp_path / "themes.json"
    path.write_text(
        json.dumps(data if data else THEMES, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def make_state(tmp_path, log=None):
    path = tmp_path / "state.json"
    if log is not None:
        path.write_text(
            json.dumps({"log": log}, ensure_ascii=False),
            encoding="utf-8",
        )
    return path


def ts_days_ago(n):
    return (datetime.now(tz=timezone.utc) - timedelta(days=n)).isoformat(timespec="seconds")


# ----------------------------------------------------------------------
# Constructor
# ----------------------------------------------------------------------

def test_init_with_existing_state(tmp_path):
    themes_path = make_themes(tmp_path)
    state_path = make_state(
        tmp_path,
        log=[{"theme_id": "fomo", "ts": ts_days_ago(1)}],
    )
    tracker = MistakeTracker(
        themes_file=str(themes_path),
        state_file=str(state_path),
    )
    assert tracker.themes == THEMES
    assert tracker.state == {"log": [{"theme_id": "fomo", "ts": ts_days_ago(1)}]}


def test_init_without_state_file(tmp_path):
    themes_path = make_themes(tmp_path)
    tracker = MistakeTracker(
        themes_file=str(themes_path),
        state_file=str(tmp_path / "state.json"),
    )
    assert tracker.state == {"log": []}


def test_init_missing_themes_file_raises(tmp_path):
    with pytest.raises((FileNotFoundError, OSError)):
        MistakeTracker(
            themes_file=str(tmp_path / "nonexistent.json"),
            state_file=str(tmp_path / "state.json"),
        )


# ----------------------------------------------------------------------
# get_next_topic()
# ----------------------------------------------------------------------

def test_get_next_topic_returns_never_used_first(tmp_path):
    themes_path = make_themes(tmp_path)
    # state: only fomo used yesterday
    state_path = make_state(
        tmp_path,
        log=[{"theme_id": "fomo", "ts": ts_days_ago(1)}],
    )
    tracker = MistakeTracker(
        themes_file=str(themes_path),
        state_file=str(state_path),
    )
    result = tracker.get_next_topic()
    assert result in ("Торговля без стопа", "Слишком большое плечо")


def test_get_next_topic_returns_oldest_when_all_used(tmp_path):
    themes_path = make_themes(tmp_path)
    # fomo today, no_stop week ago, overleverage month ago
    state_path = make_state(
        tmp_path,
        log=[
            {"theme_id": "fomo", "ts": ts_days_ago(0)},
            {"theme_id": "no_stop", "ts": ts_days_ago(7)},
            {"theme_id": "overleverage", "ts": ts_days_ago(30)},
        ],
    )
    tracker = MistakeTracker(
        themes_file=str(themes_path),
        state_file=str(state_path),
    )
    assert tracker.get_next_topic() == "Слишком большое плечо"


def test_get_next_topic_uses_latest_ts_for_repeated_theme(tmp_path):
    themes_path = make_themes(tmp_path)
    # fomo: 30 days ago, 1 hour ago, 2 days ago -> latest = 1 hour ago
    # no_stop: week ago -> 7 days
    # overleverage: 14 days ago -> 14 days
    state_path = make_state(
        tmp_path,
        log=[
            {"theme_id": "fomo", "ts": ts_days_ago(30)},
            {"theme_id": "fomo", "ts": ts_days_ago(0.04)},  # ~1 hour
            {"theme_id": "fomo", "ts": ts_days_ago(2)},
            {"theme_id": "no_stop", "ts": ts_days_ago(7)},
            {"theme_id": "overleverage", "ts": ts_days_ago(14)},
        ],
    )
    tracker = MistakeTracker(
        themes_file=str(themes_path),
        state_file=str(state_path),
    )
    assert tracker.get_next_topic() == "Слишком большое плечо"


# ----------------------------------------------------------------------
# record_usage()
# ----------------------------------------------------------------------

def test_record_usage_appends_to_log(tmp_path):
    themes_path = make_themes(tmp_path)
    state_path = make_state(tmp_path)
    tracker = MistakeTracker(
        themes_file=str(themes_path),
        state_file=str(state_path),
    )
    tracker.record_usage("fomo")
    assert len(tracker.state["log"]) == 1
    assert tracker.state["log"][0]["theme_id"] == "fomo"
    # verify ts is valid ISO
    datetime.fromisoformat(tracker.state["log"][0]["ts"])


def test_record_usage_persists_to_disk(tmp_path):
    themes_path = make_themes(tmp_path)
    state_path = make_state(tmp_path)
    tracker = MistakeTracker(
        themes_file=str(themes_path),
        state_file=str(state_path),
    )
    tracker.record_usage("no_stop")
    # read directly from disk
    with open(state_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data["log"]) == 1
    assert data["log"][0]["theme_id"] == "no_stop"


def test_record_usage_caps_log_at_200(tmp_path):
    themes_path = make_themes(tmp_path)
    # create state with 250 entries (cycle through theme_ids)
    log = []
    for i in range(250):
        tid = ["fomo", "no_stop", "overleverage"][i % 3]
        log.append({"theme_id": tid, "ts": ts_days_ago(0)})
    state_path = make_state(tmp_path, log=log)
    tracker = MistakeTracker(
        themes_file=str(themes_path),
        state_file=str(state_path),
    )
    tracker.record_usage("fomo")
    assert len(tracker.state["log"]) == 200
    assert tracker.state["log"][-1]["theme_id"] == "fomo"


# ----------------------------------------------------------------------
# weekly_report()
# ----------------------------------------------------------------------

def test_weekly_report_empty_log(tmp_path):
    themes_path = make_themes(tmp_path)
    state_path = make_state(tmp_path)
    tracker = MistakeTracker(
        themes_file=str(themes_path),
        state_file=str(state_path),
    )
    report = tracker.weekly_report()
    assert "не разбирали ошибок" in report
    # forgotten section should include never-used themes
    assert "Торговля без стопа" in report
    assert "Слишком большое плечо" in report


def test_weekly_report_top_topics(tmp_path):
    themes_path = make_themes(tmp_path)
    # fomo:5, no_stop:2, overleverage:1 all within last 7 days
    log = []
    for _ in range(5):
        log.append({"theme_id": "fomo", "ts": ts_days_ago(0)})
    for _ in range(2):
        log.append({"theme_id": "no_stop", "ts": ts_days_ago(0)})
    log.append({"theme_id": "overleverage", "ts": ts_days_ago(0)})
    state_path = make_state(tmp_path, log=log)
    tracker = MistakeTracker(
        themes_file=str(themes_path),
        state_file=str(state_path),
    )
    report = tracker.weekly_report()
    assert "FOMO трейдинг — 5 раз" in report
    assert "Торговля без стопа — 2 раз" in report


def test_weekly_report_excludes_old_records(tmp_path):
    themes_path = make_themes(tmp_path)
    # 10 fomo records older than 10 days
    log = [{"theme_id": "fomo", "ts": ts_days_ago(10 + i)} for i in range(10)]
    state_path = make_state(tmp_path, log=log)
    tracker = MistakeTracker(
        themes_file=str(themes_path),
        state_file=str(state_path),
    )
    report = tracker.weekly_report()
    assert "не разбирали ошибок" in report


def test_weekly_report_forgotten_topics_includes_never_used(tmp_path):
    themes_path = make_themes(tmp_path)
    # only fomo used
    state_path = make_state(
        tmp_path,
        log=[{"theme_id": "fomo", "ts": ts_days_ago(1)}],
    )
    tracker = MistakeTracker(
        themes_file=str(themes_path),
        state_file=str(state_path),
    )
    report = tracker.weekly_report()
    assert "Торговля без стопа" in report
    assert "Слишком большое плечо" in report


def test_weekly_report_returns_html_formatted_string(tmp_path):
    themes_path = make_themes(tmp_path)
    state_path = make_state(tmp_path)
    tracker = MistakeTracker(
        themes_file=str(themes_path),
        state_file=str(state_path),
    )
    report = tracker.weekly_report()
    assert "<b>" in report
    assert "</b>" in report