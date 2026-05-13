"""Этап 2.2: чистый content_mix без I/O.

`core.content_mix.compute_mix(log_list, now=...)` — pure function:
- mode=channel если >=CHANNEL_MODE_MIN channel-событий, иначе mode=all
- recommended=fallback при total<LOW_DATA_THRESHOLD
- иначе recommended=worst underrepresented
- иначе рекомендуем кандидата с минимальным share не из over
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.content_mix import (
    CONTENT_MIX_TARGET,
    CATEGORY_MAP,
    category_for,
    compute_mix,
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


# --- category_for -------------------------------------------------------------


def test_category_for_known_types():
    assert category_for("market") == "market_chart"
    assert category_for("ai_crypto") == "news"
    assert category_for("fallback_education") == "education"
    assert category_for("paper_trade") == "trade_diary"


def test_category_for_unknown_returns_other():
    assert category_for("totally_unknown") == "other"
    assert category_for("") == "other"


def test_category_for_strips_and_lowercases():
    assert category_for("  MARKET  ") == "market_chart"


# --- compute_mix --------------------------------------------------------------


def test_empty_log_returns_low_data_fallback():
    res = compute_mix([], now=_NOW)

    assert res["total_posts"] == 0
    assert res["recommended"] == "education"
    assert "мало данных" in res["reason"]


def test_only_owner_events_uses_mode_all():
    events = [_ev("news", published_to="owner") for _ in range(5)]
    res = compute_mix(events, now=_NOW)

    assert res["mode"] == "all"
    assert res["total_posts"] == 5


def test_three_channel_events_switches_to_channel_mode():
    events = [_ev("market_chart", published_to="channel") for _ in range(3)]
    events += [_ev("news", published_to="owner") for _ in range(10)]
    res = compute_mix(events, now=_NOW)

    assert res["mode"] == "channel"
    # Owner-события не считаются, только 3 channel
    assert res["total_posts"] == 3


def test_old_events_dropped_outside_window():
    fresh = [_ev("market_chart", days_ago=1) for _ in range(3)]
    old = [_ev("news", days_ago=20) for _ in range(10)]
    res = compute_mix(fresh + old, now=_NOW)

    assert res["total_posts"] == 3
    assert res["counts"]["market_chart"] == 3


def test_underrepresented_recommends_worst_deficit():
    # 10 market_chart (40% target, 100% actual → over) + 0 news (15% target)
    events = [_ev("market_chart") for _ in range(10)]
    res = compute_mix(events, now=_NOW)

    # news, author_note, trade_diary, education — все undertarget
    assert res["recommended"] in {"news", "author_note", "trade_diary", "education"}


def test_other_category_does_not_dilute_shares():
    events = [_ev("market_chart") for _ in range(3)]
    events += [_ev("other_unknown") for _ in range(5)]
    res = compute_mix(events, now=_NOW)

    # other не входит в target_total
    assert res["counts"]["market_chart"] == 3
    assert res["shares"]["market_chart"] == 1.0
    assert res["other_count"] == 5


def test_balanced_mix_recommends_market_chart():
    """Когда все категории в коридоре — fallback на market_chart."""
    # 4 market_chart, 2 education, 2 news, 1 author_note, 1 trade_diary = 10 total
    events = (
        [_ev("market_chart") for _ in range(4)]
        + [_ev("education") for _ in range(2)]
        + [_ev("news") for _ in range(2)]
        + [_ev("author_note") for _ in range(1)]
        + [_ev("trade_diary") for _ in range(1)]
    )
    res = compute_mix(events, now=_NOW)

    # точно в target → recommended = market_chart (default tiebreaker)
    assert res["recommended"] == "market_chart"
    assert not res["underrepresented"]


def test_result_structure():
    """Контракт возвращаемого dict — фиксируем ключи."""
    res = compute_mix([_ev("market_chart") for _ in range(3)], now=_NOW)

    for key in ("mode", "total_posts", "counts", "other_count", "shares",
                "target", "overrepresented", "underrepresented",
                "recommended", "reason"):
        assert key in res, f"missing key {key}"
