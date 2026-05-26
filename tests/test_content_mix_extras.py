import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.content_mix import (
    compute_mix,
    category_for,
    CATEGORY_MAP,
    CONTENT_MIX_TARGET,
    CONTENT_MIX_WINDOW_DAYS,
    CONTENT_MIX_CHANNEL_MODE_MIN,
    CONTENT_MIX_LOW_DATA_THRESHOLD,
)

_NOW = datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc)


def _ev(category: str, *, published_to: str = "channel", days_ago: float = 0) -> dict:
    ts = (_NOW - timedelta(days=days_ago)).isoformat(timespec="seconds")
    return {
        "timestamp": ts,
        "post_type": category,
        "category": category,
        "published_to": published_to,
        "title": "",
        "source": "test",
    }


# 1
def test_compute_mix_with_none_log_list():
    result = compute_mix(None, now=_NOW)
    assert result["total_posts"] == 0
    assert result["recommended"] == "education"
    assert isinstance(result, dict)


# 2
def test_compute_mix_invalid_timestamp_skips_event():
    valid = [_ev("market_chart", days_ago=1) for _ in range(3)]
    bad = [
        {"timestamp": "garbage", "category": "education"},
        {"timestamp": "", "category": "news"},
        {"category": "author_note"},  # нет timestamp
    ]
    events = valid + bad
    result = compute_mix(events, now=_NOW)
    assert result["total_posts"] == 3


# 3
def test_compute_mix_naive_timestamp_treated_as_utc():
    events = [
        {"timestamp": "2026-05-13T11:00:00", "category": "education"},
        {"timestamp": "2026-05-13T11:30:00", "category": "news"},
        {"timestamp": "2026-05-13T12:00:00", "category": "market_chart"},
    ]
    result = compute_mix(events, now=_NOW)
    assert result["total_posts"] == 3


# 4
def test_compute_mix_only_other_category_zero_target_total():
    events = [_ev("weird_unknown", days_ago=i) for i in range(5)]
    result = compute_mix(events, now=_NOW)
    assert result["total_posts"] == 5
    assert result["other_count"] == 5
    for c in CONTENT_MIX_TARGET:
        assert result["counts"][c] == 0
    assert result["shares"]["market_chart"] == 0.0
    assert result["recommended"] in CONTENT_MIX_TARGET


# 5
def test_compute_mix_window_boundary():
    inside = _ev("market_chart", days_ago=CONTENT_MIX_WINDOW_DAYS - 0.01)
    outside = _ev("education", days_ago=CONTENT_MIX_WINDOW_DAYS + 0.01)
    fresh = _ev("news", days_ago=0)
    result = compute_mix([inside, outside, fresh], now=_NOW)
    assert result["total_posts"] == 2


# 6
def test_compute_mix_now_defaults_to_datetime_now():
    result = compute_mix([])
    assert isinstance(result, dict)
    assert result["total_posts"] == 0


# 7
def test_category_for_none():
    assert category_for(None) == "other"


# 8
def test_category_for_all_canonical_categories_mapped():
    valid_targets = set(CONTENT_MIX_TARGET.keys()) | {"other"}
    for key in CATEGORY_MAP.keys():
        assert category_for(key) in valid_targets


# 9
def test_compute_mix_three_events_just_threshold_for_low_data():
    events = [_ev("market_chart", days_ago=i) for i in range(CONTENT_MIX_LOW_DATA_THRESHOLD)]
    result = compute_mix(events, now=_NOW)
    assert result["total_posts"] == CONTENT_MIX_LOW_DATA_THRESHOLD
    assert result["recommended"] in result["underrepresented"]
    # market_chart is 100% -> over; all others 0% -> under
    assert "market_chart" not in result["underrepresented"]


# 10
def test_compute_mix_two_events_low_data_fallback():
    events = [_ev("market_chart", days_ago=1), _ev("news", days_ago=2)]
    result = compute_mix(events, now=_NOW)
    assert result["total_posts"] == 2
    assert result["recommended"] == "education"
    assert "мало данных" in result["reason"]


# 11
def test_compute_mix_channel_mode_uses_only_channel_events():
    channel_events = [_ev("market_chart", published_to="channel", days_ago=i) for i in range(4)]
    owner_events = [_ev("news", published_to="owner", days_ago=i) for i in range(10)]
    events = channel_events + owner_events
    result = compute_mix(events, now=_NOW)
    assert result["mode"] == "channel"
    assert result["total_posts"] == 4
    assert result["counts"]["news"] == 0


# 12
def test_compute_mix_result_target_is_independent_copy():
    events = [_ev("education")]
    result1 = compute_mix(events, now=_NOW)
    result2 = compute_mix(events, now=_NOW)
    result1["target"]["market_chart"] = 999
    assert result2["target"]["market_chart"] == CONTENT_MIX_TARGET["market_chart"]