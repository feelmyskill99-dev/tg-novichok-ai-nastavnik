import datetime

import bot
from core.disclaimer import DISCLAIMER_VARIANTS


class _FakeDate(datetime.date):
    @classmethod
    def today(cls):
        return cls(2026, 5, 27)


def test_build_post_html_uses_rotated_disclaimer(monkeypatch):
    payload = {"human_part": "test post", "hashtags": ["#test"]}
    monkeypatch.setattr("bot.date", _FakeDate)
    html = bot.build_post_html(payload, post_type="market", include_partner=False, post_num=1)
    assert any(v in html for v in DISCLAIMER_VARIANTS)


def test_education_post_still_uses_long_disclaimer():
    payload = {"human_part": "edu post", "hashtags": ["#edu"]}
    html = bot.build_post_html(payload, post_type="fallback_education", include_partner=False, post_num=1)
    assert "Не является финансовым советом" in html
