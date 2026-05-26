"""Smoke test: 3 posts on 3 consecutive days should differ in disclaimer + tags."""
from __future__ import annotations

import datetime

import bot
from core.disclaimer import DISCLAIMER_VARIANTS


def _post_html(monkeypatch, today: datetime.date, *, has_hamster: bool) -> str:
    class _FakeDate(datetime.date):
        @classmethod
        def today(cls):
            return today
    monkeypatch.setattr("bot.date", _FakeDate)

    payload = {
        "human_part": "test human",
        "hamster_part": "test hamster" if has_hamster else None,
        "mentor_part": "test mentor",
        "beginner_mistake": "test mistake",
        "lesson": "test lesson",
        "hashtags": ["#BTC"],
    }
    return bot.build_post_html(payload, post_type="market", include_partner=False, post_num=1)


def test_three_consecutive_days_differ(monkeypatch):
    """3 поста на 3 разные даты дают ≥2 разных дисклеймера ИЛИ ≥2 разных вторичных тега."""
    base = datetime.date(2026, 5, 26)
    posts = [
        _post_html(monkeypatch, base + datetime.timedelta(days=i), has_hamster=True)
        for i in range(3)
    ]
    # Дисклеймеры: должны быть ≥2 разных
    found_disclaimers = set()
    for html in posts:
        for v in DISCLAIMER_VARIANTS:
            if v in html:
                found_disclaimers.add(v)
                break
    assert len(found_disclaimers) >= 2, (
        f"expected ≥2 distinct disclaimers across 3 consecutive days, got {found_disclaimers}"
    )


def test_three_days_anchor_tag_always_present(monkeypatch):
    base = datetime.date(2026, 5, 26)
    for i in range(3):
        html = _post_html(monkeypatch, base + datetime.timedelta(days=i), has_hamster=True)
        assert "#честный_путь" in html, f"day {i}: missing anchor tag"
