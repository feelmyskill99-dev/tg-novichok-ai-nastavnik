import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from news.drafts import (
    NewsDraft, MAX_DRAFTS,
    REGENERATE_INSTRUCTION, REVISE_INSTRUCTION,
    _source_news_for_claude,
)


def _mk_draft(
    *,
    source_news_overrides: dict | None = None,
    claude_json: dict | None = None,
    revision_count: int = 0,
) -> NewsDraft:
    if source_news_overrides is not None:
        # Полная замена — позволяет тестам передать subset с пропущенными ключами.
        base = dict(source_news_overrides)
    else:
        base = {
            "id": "n1",
            "title": "BTC ETF approved by SEC",
            "url": "https://example.com/n1",
            "source": "CoinDesk",
            "published_at": "2026-05-14T09:00:00+00:00",
            "summary": "Long summary text",
            "assets": ["BTC"],
            "category": "etf_institutional",
            "sector": "regulation_etf_institutional",
            "impact_score": 88.0,
        }
    return NewsDraft(
        draft_id="d1",
        created_at="2026-05-14T10:00:00+00:00",
        status="pending_review",
        source_news=base,
        post_html="<b>orig post</b>",
        claude_json=claude_json or {"specific_title": "BTC ETF approved"},
        revision_count=revision_count,
    )


class TestConstants:
    def test_max_drafts_is_positive_int(self):
        assert isinstance(MAX_DRAFTS, int)
        assert MAX_DRAFTS > 0

    def test_regenerate_instruction_mentions_facts(self):
        assert "факт" in REGENERATE_INSTRUCTION.lower()

    def test_regenerate_instruction_mentions_url(self):
        assert "url" in REGENERATE_INSTRUCTION.lower()

    def test_regenerate_instruction_no_markdown_wrapper(self):
        assert "json" in REGENERATE_INSTRUCTION.lower()

    def test_revise_instruction_mentions_facts(self):
        assert "факт" in REVISE_INSTRUCTION.lower()

    def test_revise_instruction_forbids_signals(self):
        assert "сигнал" in REVISE_INSTRUCTION.lower()

    def test_revise_instruction_forbids_profit_promises(self):
        assert "прибыл" in REVISE_INSTRUCTION.lower()


class TestSourceNewsForClaude:
    def test_source_news_includes_all_required_keys(self):
        draft = _mk_draft()
        result = _source_news_for_claude(draft)
        expected = {"id", "title", "url", "source", "published_at", "summary",
                    "assets", "category", "sector", "impact_score"}
        assert set(result.keys()) == expected

    def test_source_news_summary_under_400_unchanged(self):
        summary = "x" * 100
        draft = _mk_draft(source_news_overrides={"summary": summary})
        result = _source_news_for_claude(draft)
        assert result["summary"] == summary

    def test_source_news_summary_at_exactly_400_unchanged(self):
        summary = "x" * 400
        draft = _mk_draft(source_news_overrides={"summary": summary})
        result = _source_news_for_claude(draft)
        assert result["summary"] == summary

    def test_source_news_summary_over_400_truncated(self):
        summary = "x" * 500
        draft = _mk_draft(source_news_overrides={"summary": summary})
        result = _source_news_for_claude(draft)
        assert len(result["summary"]) == 400

    def test_source_news_empty_summary_returns_empty_string(self):
        draft = _mk_draft(source_news_overrides={"summary": ""})
        result = _source_news_for_claude(draft)
        assert result["summary"] == ""

    def test_source_news_missing_summary_returns_empty_string(self):
        base = {
            "id": "n1",
            "title": "BTC ETF approved by SEC",
            "url": "https://example.com/n1",
            "source": "CoinDesk",
            "published_at": "2026-05-14T09:00:00+00:00",
            "assets": ["BTC"],
            "category": "etf_institutional",
            "sector": "regulation_etf_institutional",
            "impact_score": 88.0,
        }
        draft = _mk_draft(source_news_overrides=base)  # no "summary" key
        result = _source_news_for_claude(draft)
        assert result["summary"] == ""

    def test_source_news_missing_assets_returns_empty_list(self):
        base = {
            "id": "n1",
            "title": "BTC ETF approved by SEC",
            "url": "https://example.com/n1",
            "source": "CoinDesk",
            "published_at": "2026-05-14T09:00:00+00:00",
            "summary": "text",
            "category": "etf_institutional",
            "sector": "regulation_etf_institutional",
            "impact_score": 88.0,
        }
        draft = _mk_draft(source_news_overrides=base)
        result = _source_news_for_claude(draft)
        assert result["assets"] == []

    def test_source_news_impact_score_zero_when_missing(self):
        base = {
            "id": "n1",
            "title": "BTC ETF",
            "url": "https://example.com/n1",
            "source": "CoinDesk",
            "published_at": "2026-05-14T09:00:00+00:00",
            "summary": "text",
            "assets": ["BTC"],
            "category": "etf_institutional",
            "sector": "regulation_etf_institutional",
        }
        draft = _mk_draft(source_news_overrides=base)
        result = _source_news_for_claude(draft)
        assert result["impact_score"] == 0

    def test_source_news_impact_score_zero_when_none(self):
        draft = _mk_draft(source_news_overrides={"impact_score": None})
        result = _source_news_for_claude(draft)
        assert result["impact_score"] == 0

    def test_source_news_preserves_assets_list(self):
        assets = ["BTC", "ETH"]
        draft = _mk_draft(source_news_overrides={"assets": assets})
        result = _source_news_for_claude(draft)
        assert result["assets"] == assets

    def test_source_news_preserves_url_unchanged(self):
        url = "https://example.com/n1"
        draft = _mk_draft(source_news_overrides={"url": url})
        result = _source_news_for_claude(draft)
        assert result["url"] == url


class TestNewsDraftRevisionCount:
    def test_news_draft_revision_count_default_zero(self):
        draft = NewsDraft(
            draft_id="d1",
            created_at="2026-05-14T10:00:00+00:00",
            status="pending_review",
            source_news={"id": "n1"},
            post_html="<p>test</p>",
            claude_json={},
        )
        assert draft.revision_count == 0

    def test_news_draft_revision_count_increment_via_dataclass(self):
        draft = _mk_draft(revision_count=0)
        draft.revision_count = 3
        assert draft.revision_count == 3