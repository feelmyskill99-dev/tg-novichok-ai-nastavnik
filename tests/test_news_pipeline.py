from __future__ import annotations
import sys, json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from news.models import NewsItem, make_news_id, CATEGORIES, SECTORS
from news.cache import NewsCache
from news.deduplicator import NewsDeduplicator, _tokenize_title, TITLE_SIMILARITY_THRESHOLD
from news.scorer import NewsScorer
from news.config import NewsConfig


def _mk_item(
    *,
    title: str = "BlackRock spot ETF approval by SEC sees record inflows",
    url: str = "https://example.com/news/1",
    source: str = "CoinDesk",
    summary: str = "",
    assets: list[str] | None = None,
    published_at: str | None = None,
) -> NewsItem:
    published_at = published_at or datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
    return NewsItem(
        title=title,
        url=url,
        source=source,
        published_at=published_at,
        summary=summary,
        assets=assets or [],
    )


# ---------------------------------------------------------------------------
# NewsItem (~6 тестов)
# ---------------------------------------------------------------------------

class TestNewsItem:
    def test_news_item_post_init_generates_id(self):
        item = _mk_item()
        assert len(item.id) == 16
        assert all(c in "0123456789abcdef" for c in item.id)

    def test_news_item_assets_uppercased_and_stripped(self):
        item = _mk_item(assets=["btc ", " eth"])
        assert item.assets == ["BTC", "ETH"]

    def test_news_item_collected_at_auto_set(self):
        item = _mk_item()
        assert item.collected_at != ""
        # valid ISO format (rough check)
        assert "T" in item.collected_at

    def test_make_news_id_stable_for_same_title_source(self):
        id1 = make_news_id("Hello World", "CoinDesk")
        id2 = make_news_id("Hello World", "CoinDesk")
        assert id1 == id2

    def test_make_news_id_same_after_normalization(self):
        # _normalize_title делает lower().strip().split() — без удаления пунктуации.
        id1 = make_news_id("  Hello   World ", "COINDESK")
        id2 = make_news_id("hello world", "coindesk")
        assert id1 == id2

    def test_news_item_to_dict_round_trip(self):
        item = _mk_item(title="Test", url="http://x.com", source="Src",
                        assets=["ETH", "BTC"])
        d = item.to_dict()
        restored = NewsItem.from_dict(d)
        assert restored.id == item.id
        assert restored.title == item.title
        assert restored.url == item.url
        assert restored.assets == item.assets


# ---------------------------------------------------------------------------
# NewsCache (~3 теста)
# ---------------------------------------------------------------------------

class TestNewsCache:
    def test_news_cache_save_load_round_trip(self, tmp_path: Path):
        cache = NewsCache(tmp_path / "cache.json")
        items = [
            _mk_item(title="First", url="http://a.com", source="S1"),
            _mk_item(title="Second", url="http://b.com", source="S2"),
        ]
        cache.save(items)
        loaded = cache.load()
        assert len(loaded) == 2
        assert loaded[0].id == items[0].id
        assert loaded[1].id == items[1].id

    def test_news_cache_load_missing_returns_empty(self, tmp_path: Path):
        cache = NewsCache(tmp_path / "nonexistent.json")
        assert cache.load() == []

    def test_news_cache_load_corrupt_returns_empty(self, tmp_path: Path):
        f = tmp_path / "corrupt.json"
        f.write_text("not json", encoding="utf-8")
        cache = NewsCache(f)
        assert cache.load() == []


# ---------------------------------------------------------------------------
# NewsDeduplicator (~6 тестов)
# ---------------------------------------------------------------------------

class TestNewsDeduplicator:
    def test_dedup_empty_history_not_duplicate(self, tmp_path: Path):
        dedup = NewsDeduplicator(tmp_path / "h.json")
        item = _mk_item()
        assert not dedup.is_duplicate(item)

    def test_dedup_remember_then_duplicate(self, tmp_path: Path):
        dedup = NewsDeduplicator(tmp_path / "h.json")
        item = _mk_item()
        dedup.remember(item, "published_channel")
        assert dedup.is_duplicate(item)

    def test_dedup_url_match_is_duplicate(self, tmp_path: Path):
        dedup = NewsDeduplicator(tmp_path / "h.json")
        item1 = _mk_item(title="News A", url="https://example.com/abc", source="S1")
        item2 = _mk_item(title="News B", url="https://example.com/abc", source="S2")
        dedup.remember(item1, "published_channel")
        assert dedup.is_duplicate(item2)

    def test_dedup_similar_title_cross_source_is_duplicate(self, tmp_path: Path):
        dedup = NewsDeduplicator(tmp_path / "h.json")
        title1 = "BlackRock Bitcoin ETF sees record inflows of $500M today"
        title2 = "BlackRock Bitcoin ETF records record inflows totaling $500M today"
        item1 = _mk_item(title=title1, url="http://a.com", source="CoinDesk")
        item2 = _mk_item(title=title2, url="http://b.com", source="Decrypt")
        # manually compute similarity to ensure it's above threshold
        tokens1 = _tokenize_title(title1)
        tokens2 = _tokenize_title(title2)
        from difflib import SequenceMatcher
        ratio = SequenceMatcher(None, tokens1, tokens2).ratio()
        assert ratio >= TITLE_SIMILARITY_THRESHOLD, f"ratio {ratio} < {TITLE_SIMILARITY_THRESHOLD}"
        dedup.remember(item1, "published_channel")
        assert dedup.is_duplicate(item2)

    def test_dedup_unrelated_titles_not_duplicate(self, tmp_path: Path):
        dedup = NewsDeduplicator(tmp_path / "h.json")
        item1 = _mk_item(title="Bitcoin ETF approval", url="http://a.com", source="S1")
        item2 = _mk_item(title="Solana memecoin pump", url="http://b.com", source="S2")
        dedup.remember(item1, "published_channel")
        assert not dedup.is_duplicate(item2)

    def test_dedup_old_record_outside_window_not_duplicate(self, tmp_path: Path):
        dedup = NewsDeduplicator(tmp_path / "h.json", window_hours=48)
        # manually write an old record
        old_time = (datetime.now(tz=timezone.utc) - timedelta(hours=72)).isoformat(timespec="seconds")
        item = _mk_item(title="Old news", url="http://old.com", source="S")
        record = {
            "title_hash": item.id,
            "title": item.title,
            "url": item.url,
            "source": item.source,
            "posted_at": old_time,
            "impact_score": 0.0,
            "sector": "other",
            "decision": "published_channel",
            "short_summary": "",
        }
        dedup._save([record])
        # same item now should NOT be duplicate (outside window)
        new_item = _mk_item(title="Old news", url="http://old.com", source="S")
        assert not dedup.is_duplicate(new_item)


# ---------------------------------------------------------------------------
# NewsScorer (~5 тестов)
# ---------------------------------------------------------------------------

class TestNewsScorer:
    def test_scorer_detects_etf_sector_and_high_base(self):
        # Без слова "BlackRock" — оно ловится в rwa_tokenization, который
        # проверяется в SECTOR_KEYWORDS раньше regulation_etf_institutional.
        config = NewsConfig()
        scorer = NewsScorer(config)
        item = _mk_item(
            title="Spot ETF approval by SEC sees institutional inflows",
            source="CoinDesk",
            assets=["BTC"],
        )
        scored = scorer.score(item)
        assert scored.sector == "regulation_etf_institutional"
        assert scored.impact_score >= 85

    def test_scorer_memecoin_zero_when_disabled(self):
        config = NewsConfig()  # news_allow_memecoins defaults to False
        scorer = NewsScorer(config)
        item = _mk_item(
            title="DOGE pumps 200% on memecoin frenzy",
            source="CoinDesk",
            assets=["DOGE"],
        )
        scored = scorer.score(item)
        assert scored.sector == "memecoins_low_priority"
        assert scored.impact_score == 0.0

    def test_scorer_price_prediction_penalty(self):
        config = NewsConfig()
        scorer = NewsScorer(config)
        base_item = _mk_item(
            title="Bitcoin price reaches new high",
            source="CoinDesk",
            assets=["BTC"],
        )
        pred_item = _mk_item(
            title="Bitcoin price prediction: BTC could hit $200K by 2026",
            source="CoinDesk",
            assets=["BTC"],
        )
        base_score = scorer.score(base_item).impact_score
        pred_score = scorer.score(pred_item).impact_score
        assert pred_score < base_score

    def test_scorer_sketchy_source_penalty(self):
        config = NewsConfig()
        scorer = NewsScorer(config)
        trusted_item = _mk_item(
            title="Bitcoin ETF approved",
            source="CoinDesk",
            assets=["BTC"],
        )
        sketchy_item = _mk_item(
            title="Bitcoin ETF approved",
            source="some-blog.medium.com",
            assets=["BTC"],
        )
        trusted_score = scorer.score(trusted_item).impact_score
        sketchy_score = scorer.score(sketchy_item).impact_score
        assert sketchy_score < trusted_score  # -50 penalty

    def test_scorer_score_clamped_0_100(self):
        config = NewsConfig()
        scorer = NewsScorer(config)
        # high-impact item with many bonuses
        item = _mk_item(
            title="BlackRock spot ETF approval by SEC sees record inflows institutional custody",
            source="CoinDesk",
            assets=["BTC", "ETH"],
            published_at=datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
        )
        scored = scorer.score(item, similar_count=5)
        assert 0 <= scored.impact_score <= 100
        # low-score item (sketchy source, price prediction)
        low_item = _mk_item(
            title="Bitcoin price prediction: BTC could hit $200K by 2026",
            source="some-blog.medium.com",
            assets=[],
        )
        low_scored = scorer.score(low_item)
        assert 0 <= low_scored.impact_score <= 100