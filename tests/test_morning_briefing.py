import json
import httpx
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest

from core.fear_greed import fetch_fear_greed, fetch_fear_greed_raw, _label_from_value
from core.morning_briefing import (
    build_morning_briefing_html,
    fetch_top_news_for_briefing,
)

# =============== core/fear_greed.py ===============

NOW = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc)


class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_label_strong_fear():
    assert _label_from_value(10) == "сильный страх"


def test_label_fear():
    assert _label_from_value(30) == "страх"


def test_label_neutral():
    assert _label_from_value(50) == "нейтрально"


def test_label_greed():
    assert _label_from_value(60) == "жадность"


def test_label_strong_greed():
    assert _label_from_value(85) == "сильная жадность"


def test_fetch_raw_success(monkeypatch):
    def fake_get(*args, **kwargs):
        return _FakeResp(200, {"data": [{"value": "42"}]})
    monkeypatch.setattr(httpx, "get", fake_get)
    result = fetch_fear_greed_raw(timeout_s=5.0)
    assert result == 42


def test_fetch_raw_http_error(monkeypatch):
    def fake_get(*args, **kwargs):
        return _FakeResp(500, {})
    monkeypatch.setattr(httpx, "get", fake_get)
    result = fetch_fear_greed_raw(timeout_s=5.0)
    assert result is None


def test_fetch_with_cache_hit(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    # cached_at должен быть «свежий» относительно ВРЕМЕНИ запуска теста.
    # TTL = 3600s, поэтому ставим cached_at = now - 5min, чтобы кэш был валиден.
    from datetime import datetime, timezone, timedelta
    fresh_ts = (datetime.now(tz=timezone.utc) - timedelta(minutes=5)).isoformat(timespec="seconds")
    cache = {
        "fear_greed_cache": {
            "value": 50,
            "cached_at": fresh_ts,
        }
    }
    state_path.write_text(json.dumps(cache), encoding="utf-8")

    def fail_get(*args, **kwargs):
        raise AssertionError("httpx.get should not be called")
    monkeypatch.setattr(httpx, "get", fail_get)

    value, label = fetch_fear_greed(state_path=state_path)
    assert value == 50
    assert label == "нейтрально"


# =============== core/morning_briefing.py ===============

def test_build_basic():
    market = {"price": 75000, "change_24h": -1.4}
    news = [
        {"title": "News1", "url": "https://example.com/1"},
        {"title": "News2", "url": "https://example.com/2"},
        {"title": "News3", "url": "https://example.com/3"},
    ]
    html = build_morning_briefing_html(
        market, news,
        fg_index=25, fg_label="страх",
        partner_url="https://gate.io/ref",
        bot_username="@ai_deposit_diary_bot",
        channel_id_for_links="@chan",
        caption_limit=1024,
    )
    assert "🌅 <b>Доброе утро!</b>" in html
    assert "BTC у $75 000" in html
    assert "(-1.40%)" in html
    assert "в минусе" in html


def test_build_direction_plus():
    market = {"price": 50000, "change_24h": 2.5}
    html = build_morning_briefing_html(market, [], caption_limit=1024)
    assert "в плюсе" in html


def test_build_direction_minus():
    market = {"price": 50000, "change_24h": -1.5}
    html = build_morning_briefing_html(market, [], caption_limit=1024)
    assert "в минусе" in html


def test_build_direction_sideways():
    market = {"price": 50000, "change_24h": 0.3}
    html = build_morning_briefing_html(market, [], caption_limit=1024)
    assert "в боковике" in html


def test_build_fg_optional():
    # case 1: fg_index=None → no F&G line
    html_no = build_morning_briefing_html(
        {"price": 50000, "change_24h": 0.0}, [],
        fg_index=None, fg_label="", caption_limit=1024
    )
    assert "Индекс F&amp;G" not in html_no

    # case 2: fg_index=25, label="страх" → includes line
    html_yes = build_morning_briefing_html(
        {"price": 50000, "change_24h": 0.0}, [],
        fg_index=25, fg_label="страх", caption_limit=1024
    )
    assert "Индекс F&amp;G: 25 — страх." in html_yes


def test_news_message_id_renders_as_internal_link():
    news = [{"title": "Title", "message_id": 110}]
    html = build_morning_briefing_html(
        {"price": 50000, "change_24h": 0}, news,
        channel_id_for_links="@chan", caption_limit=1024
    )
    assert '<a href="https://t.me/chan/110">' in html


def test_news_external_url_when_no_message_id():
    news = [{"title": "Title", "url": "https://example.com/x"}]
    html = build_morning_briefing_html(
        {"price": 50000, "change_24h": 0}, news,
        channel_id_for_links="@chan", caption_limit=1024
    )
    assert '<a href="https://example.com/x">' in html


def test_news_no_url_no_msgid_plain():
    news = [{"title": "Plain title"}]
    html = build_morning_briefing_html(
        {"price": 50000, "change_24h": 0}, news,
        caption_limit=1024
    )
    assert "<a href" not in html
    assert "Plain title" in html


def test_caption_limit_drops_to_3_news():
    # Длинные заголовки чтобы 5 не влезали в caption=300, но 3 — да.
    long_news = [{"title": f"Длинный заголовок номер {i} с дополнительным текстом для веса"} for i in range(5)]
    html = build_morning_briefing_html(
        {"price": 50000, "change_24h": 0}, long_news,
        caption_limit=300
    )
    bullet_count = html.count("➤")
    assert bullet_count <= 3
    assert len(html) <= 300


def test_html_escapes_titles():
    news = [{"title": "Hack <script>"}]
    html = build_morning_briefing_html(
        {"price": 50000, "change_24h": 0}, news,
        caption_limit=1024
    )
    assert "&lt;script&gt;" in html
    assert "<script>" not in html


def _make_draft(*, draft_id, status, impact, created_at=None, title=None):
    if created_at is None:
        created_at = NOW.isoformat(timespec="seconds")
    return {
        "draft_id": draft_id,
        "created_at": created_at,
        "status": status,
        "source_news": {
            "title": title or f"news_{draft_id}",
            "url": f"https://src/{draft_id}",
            "impact_score": impact,
            "source": "test",
            "published_at": "",
            "summary": "",
            "assets": [],
            "category": "other",
            "sector": "ai_crypto",
            "id": draft_id,
        },
        "claude_json": {"specific_title": title or f"specific_{draft_id}"},
        "post_html": "...",
        "revision_count": 0,
        "owner_feedback": [],
        "updated_at": "",
    }


def test_fetch_only_published(tmp_path):
    drafts = [
        _make_draft(draft_id="1", status="published", impact=80),
        _make_draft(draft_id="2", status="pending_review", impact=70),
        _make_draft(draft_id="3", status="rejected", impact=60),
    ]
    path = tmp_path / "news_drafts.json"
    path.write_text(json.dumps(drafts), encoding="utf-8")
    result = fetch_top_news_for_briefing(path, now=NOW, lookback_hours=24, limit=5)
    assert len(result) == 1
    assert result[0]["title"] == "specific_1"


def test_fetch_within_lookback_window(tmp_path):
    drafts = [
        _make_draft(
            draft_id="1", status="published", impact=90,
            created_at=(NOW - timedelta(hours=5)).isoformat(timespec="seconds")
        ),
        _make_draft(
            draft_id="2", status="published", impact=80,
            created_at=(NOW - timedelta(hours=20)).isoformat(timespec="seconds")
        ),
    ]
    path = tmp_path / "news_drafts.json"
    path.write_text(json.dumps(drafts), encoding="utf-8")
    result = fetch_top_news_for_briefing(path, now=NOW, lookback_hours=14, limit=5)
    assert len(result) == 1
    assert result[0]["title"] == "specific_1"


def test_fetch_sorts_by_impact_desc(tmp_path):
    drafts = [
        _make_draft(draft_id="a", status="published", impact=50),
        _make_draft(draft_id="b", status="published", impact=90),
        _make_draft(draft_id="c", status="published", impact=70),
    ]
    path = tmp_path / "news_drafts.json"
    path.write_text(json.dumps(drafts), encoding="utf-8")
    result = fetch_top_news_for_briefing(path, now=NOW, lookback_hours=24, limit=5)
    # title формата "specific_<id>" → проверяем что порядок id'ов соответствует impact desc
    assert [r["title"].split("_")[1] for r in result] == ["b", "c", "a"]  # b=90, c=70, a=50


def test_fetch_limit(tmp_path):
    drafts = [
        _make_draft(draft_id=str(i), status="published", impact=50)
        for i in range(10)
    ]
    path = tmp_path / "news_drafts.json"
    path.write_text(json.dumps(drafts), encoding="utf-8")
    result = fetch_top_news_for_briefing(path, now=NOW, lookback_hours=24, limit=3)
    assert len(result) == 3


def test_fetch_missing_file(tmp_path):
    path = tmp_path / "nonexistent.json"
    result = fetch_top_news_for_briefing(path, now=NOW, lookback_hours=24, limit=5)
    assert result == []