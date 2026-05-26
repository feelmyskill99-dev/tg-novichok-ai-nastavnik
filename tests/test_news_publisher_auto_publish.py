"""NEWS_AUTO_PUBLISH_MIN_IMPACT — bypass ручного ревью для новостей с высоким impact.

Контракт фичи:
- news_auto_publish_min_impact == 0 → старое поведение (всё в ревью).
- news_auto_publish_min_impact > 0 и item.impact_score >= порога → публикация
  в канал даже если news_publish_to_channel=False.
- Остальные предохранители продолжают действовать:
  news_dry_run, enable_news, news_max_posts_per_day, dedup, guard.
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from news.config import NewsConfig
from news.deduplicator import NewsDeduplicator
from news.models import NewsItem
from news.publisher import NewsPublisher


def _make_cfg(**overrides) -> NewsConfig:
    base = NewsConfig(
        enable_news=True,
        news_dry_run=False,
        news_min_impact_score=50,
        news_max_posts_per_day=10,
        news_publish_to_channel=False,   # ключевое: ручной флаг ВЫКЛЮЧЕН
        news_send_to_owner=True,
        news_auto_publish_min_impact=0,  # дефолт — bypass выключен
        news_format_version="v2",
    )
    return replace(base, **overrides)


def _make_item(impact: float = 95.0) -> NewsItem:
    return NewsItem(
        title="ETF одобрен SEC: первый спотовый Solana-ETF получил зелёный свет",
        url="https://example.com/sol-etf-approved",
        source="bloomberg",
        published_at="2026-05-26T10:00:00+00:00",
        summary="SEC approved",
        assets=["SOL"],
        category="regulation",
        sector="regulation_etf_institutional",
        impact_score=impact,
    )


def _make_valid_v2_payload() -> dict:
    return {
        "should_publish": True,
        "specific_title": "SEC одобрил спотовый Solana-ETF",
        "lead": (
            "После полугода ожидания комиссия наконец дала зелёный свет: "
            "спотовый Solana-ETF будет торговаться на NYSE уже в июне."
        ),
        "facts": [
            "Решение SEC принято 5 голосами против 0 — редкое единогласие.",
            "Эмитенты — три крупных управляющих, среди них VanEck и 21Shares.",
            "Старт торгов запланирован на 9 июня, объёмы оцениваются в $500M.",
        ],
        "newbie_voice": (
            "Я не покупаю на хайпе. Просто смотрю, как реагирует цена, "
            "и записываю что чувствую."
        ),
        "tone": "calm",
        "short_summary": "одобрен Solana-ETF",
        "hashtags": ["#ETF"],
    }


class _FakeDedup:
    """Мок NewsDeduplicator: всё in-memory, без файлов."""

    def __init__(self, *, posted_today_count: int = 0):
        self.is_duplicate_value = False
        self._posted_today = posted_today_count
        self.remembered: list[tuple[str, str]] = []  # (decision, title)

    def is_duplicate(self, item):
        return self.is_duplicate_value

    def remember(self, item, decision, **_):
        self.remembered.append((decision, item.title))

    def posted_today(self, *, only_channel: bool = False):
        return self._posted_today


class _SendRecorder:
    def __init__(self):
        self.channel_calls: list[tuple[str, str]] = []   # (chat_id, html_excerpt)
        self.owner_calls: list[tuple[str, str]] = []

    def make_send_fn(self, channel_id: str, owner_id: str):
        async def _send(chat_id, html_text, image_path):
            if chat_id == channel_id:
                self.channel_calls.append((chat_id, html_text[:100]))
            else:
                self.owner_calls.append((chat_id, html_text[:100]))
        return _send

    def make_preview_send(self):
        self.preview_calls: list[tuple[str, dict]] = []

        async def _preview(html_text, kb_dict, image_path, meta):
            self.preview_calls.append((html_text[:100], meta or {}))
        return _preview


def _make_publisher(cfg: NewsConfig, *, dedup=None, channel_id="@chan", owner_id="123",
                    draft_store=None, recorder=None):
    recorder = recorder or _SendRecorder()
    send_fn = recorder.make_send_fn(channel_id, owner_id)
    preview_send = recorder.make_preview_send()
    publisher = NewsPublisher(
        config=cfg,
        dedup=dedup or _FakeDedup(),
        owner_chat_id=owner_id,
        channel_id=channel_id,
        send_fn=send_fn,
        draft_store=draft_store,
        preview_send_fn=preview_send,
    )
    return publisher, recorder


# --- Config flag plumbing ----------------------------------------------------


def test_default_auto_publish_threshold_is_zero():
    cfg = NewsConfig()
    assert cfg.news_auto_publish_min_impact == 0


def test_auto_publish_threshold_loads_from_env(monkeypatch):
    monkeypatch.setenv("NEWS_AUTO_PUBLISH_MIN_IMPACT", "85")
    cfg = NewsConfig.from_env()
    assert cfg.news_auto_publish_min_impact == 85


def test_auto_publish_threshold_default_when_env_missing(monkeypatch):
    monkeypatch.delenv("NEWS_AUTO_PUBLISH_MIN_IMPACT", raising=False)
    cfg = NewsConfig.from_env()
    assert cfg.news_auto_publish_min_impact == 0


# --- Behaviour: bypass triggers ----------------------------------------------


@pytest.mark.asyncio
async def test_high_impact_publishes_to_channel_without_manual_flag():
    """impact=95, threshold=90 → канал, хотя news_publish_to_channel=False."""
    cfg = _make_cfg(news_auto_publish_min_impact=90)
    publisher, rec = _make_publisher(cfg)

    decision = await publisher.publish(_make_valid_v2_payload(), _make_item(impact=95))

    assert decision == "published_channel", f"got {decision!r}"
    assert len(rec.channel_calls) == 1
    assert not rec.preview_calls


@pytest.mark.asyncio
async def test_low_impact_goes_to_review_when_below_threshold():
    """impact=80, threshold=90 → ревью владельцу."""
    cfg = _make_cfg(news_auto_publish_min_impact=90)

    # Чтобы получить 'preview_sent' нужен draft_store. Без него — fallback 'sent_owner'.
    # Для теста факта 'не в канал' достаточно проверить, что channel_calls пуст.
    publisher, rec = _make_publisher(cfg)
    decision = await publisher.publish(_make_valid_v2_payload(), _make_item(impact=80))

    assert decision != "published_channel"
    assert not rec.channel_calls


@pytest.mark.asyncio
async def test_threshold_zero_disables_bypass():
    """threshold=0 → даже impact=100 идёт в ревью (старое поведение)."""
    cfg = _make_cfg(news_auto_publish_min_impact=0)
    publisher, rec = _make_publisher(cfg)

    decision = await publisher.publish(_make_valid_v2_payload(), _make_item(impact=100))

    assert decision != "published_channel"
    assert not rec.channel_calls


@pytest.mark.asyncio
async def test_impact_exactly_at_threshold_publishes():
    """impact == threshold (граница) → в канал."""
    cfg = _make_cfg(news_auto_publish_min_impact=90)
    publisher, rec = _make_publisher(cfg)

    decision = await publisher.publish(_make_valid_v2_payload(), _make_item(impact=90))

    assert decision == "published_channel"


# --- Behaviour: safety nets still hold ---------------------------------------


@pytest.mark.asyncio
async def test_dry_run_blocks_auto_publish():
    """news_dry_run=True → даже при impact >= threshold не публикуем."""
    cfg = _make_cfg(news_auto_publish_min_impact=90, news_dry_run=True)
    publisher, rec = _make_publisher(cfg)

    decision = await publisher.publish(_make_valid_v2_payload(), _make_item(impact=95))

    assert decision != "published_channel"
    assert not rec.channel_calls


@pytest.mark.asyncio
async def test_enable_news_false_blocks_auto_publish():
    cfg = _make_cfg(news_auto_publish_min_impact=90, enable_news=False)
    publisher, rec = _make_publisher(cfg)

    decision = await publisher.publish(_make_valid_v2_payload(), _make_item(impact=95))

    assert decision != "published_channel"
    assert not rec.channel_calls


@pytest.mark.asyncio
async def test_max_posts_per_day_blocks_auto_publish():
    """Лимит дня всё ещё работает даже при impact bypass."""
    cfg = _make_cfg(news_auto_publish_min_impact=90, news_max_posts_per_day=2)
    dedup = _FakeDedup(posted_today_count=2)  # уже на лимите
    publisher, rec = _make_publisher(cfg, dedup=dedup)

    decision = await publisher.publish(_make_valid_v2_payload(), _make_item(impact=95))

    assert decision != "published_channel"
    assert not rec.channel_calls


@pytest.mark.asyncio
async def test_duplicate_blocks_auto_publish():
    cfg = _make_cfg(news_auto_publish_min_impact=90)
    dedup = _FakeDedup()
    dedup.is_duplicate_value = True
    publisher, rec = _make_publisher(cfg, dedup=dedup)

    decision = await publisher.publish(_make_valid_v2_payload(), _make_item(impact=95))

    assert decision == "skipped"
    assert not rec.channel_calls


@pytest.mark.asyncio
async def test_manual_flag_still_works_alongside_bypass():
    """news_publish_to_channel=True работает и без threshold (backward compat)."""
    cfg = _make_cfg(
        news_publish_to_channel=True,
        news_auto_publish_min_impact=0,  # threshold выключен
    )
    publisher, rec = _make_publisher(cfg)

    decision = await publisher.publish(_make_valid_v2_payload(), _make_item(impact=60))

    assert decision == "published_channel"
    assert len(rec.channel_calls) == 1
