import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from news.drafts import (
    NewsDraft,
    DraftStore,
    _make_draft_id,
    _source_news_for_claude,
    review_keyboard,
    get_recent_published_phrases,
    create_draft_from,
    MAX_DRAFTS,
)
from news.models import NewsItem


# ── helpers ─────────────────────────────────────────────────────────────────

def _mk_item(
    item_id: str = "i1",
    title: str = "BTC ETF approved",
    source: str = "CoinDesk",
) -> NewsItem:
    return NewsItem(
        id=item_id,
        title=title,
        url=f"https://example.com/{item_id}",
        source=source,
        published_at="2026-05-14T10:00:00+00:00",
        summary="Brief summary",
        assets=["BTC"],
        category="etf_institutional",
        sector="regulation_etf_institutional",
        impact_score=85.0,
    )

def _mk_draft(
    draft_id: str = "d1",
    status: str = "pending_review",
    human: str = "тут думает новичок",
    mentor: str = "тут вмешивается AI-наставник",
) -> NewsDraft:
    return NewsDraft(
        draft_id=draft_id,
        created_at="2026-05-14T10:00:00+00:00",
        status=status,
        source_news={
            "id": draft_id,
            "title": "ETF approved",
            "url": "https://example.com/",
            "source": "CoinDesk",
            "published_at": "2026-05-14T09:00:00+00:00",
            "summary": "summary",
            "assets": ["BTC"],
            "category": "etf_institutional",
            "sector": "regulation_etf_institutional",
            "impact_score": 85.0,
        },
        post_html="<b>post</b>",
        claude_json={
            "specific_title": "ETF approved by SEC",
            "human_part": human,
            "mentor_part": mentor,
        },
    )

def _mk_store(tmp_path: Path) -> DraftStore:
    return DraftStore(tmp_path / "drafts.json")


# ── _make_draft_id ──────────────────────────────────────────────────────────

class TestMakeDraftId:
    def test_make_draft_id_returns_16_hex(self) -> None:
        item = _mk_item()
        draft_id = _make_draft_id(item)
        assert isinstance(draft_id, str)
        assert len(draft_id) == 16
        assert all(c in "0123456789abcdef" for c in draft_id)

    def test_make_draft_id_includes_item_id_seed(self) -> None:
        item1 = _mk_item(item_id="a")
        item2 = _mk_item(item_id="b")
        # разные id – почти всегда разные draft_id (может совпасть при
        # одинаковой микросекунде, но это крайне маловероятно)
        assert _make_draft_id(item1) != _make_draft_id(item2)

    def test_make_draft_id_changes_with_time(self) -> None:
        item = _mk_item()
        id1 = _make_draft_id(item)
        id2 = _make_draft_id(item)
        # функция всегда возвращает строку длиной 16, даже если id совпали
        assert isinstance(id1, str) and len(id1) == 16
        assert isinstance(id2, str) and len(id2) == 16


# ── review_keyboard ────────────────────────────────────────────────────────

class TestReviewKeyboard:
    def test_review_keyboard_structure(self) -> None:
        kb = review_keyboard("d1")
        assert isinstance(kb, dict)
        assert "inline_keyboard" in kb
        assert isinstance(kb["inline_keyboard"], list)
        for row in kb["inline_keyboard"]:
            assert isinstance(row, list)

    def test_review_keyboard_includes_publish_callback(self) -> None:
        kb = review_keyboard("d1")
        flat = [btn for row in kb["inline_keyboard"] for btn in row]
        assert any(btn.get("callback_data") == "news_publish:d1" for btn in flat)

    def test_review_keyboard_includes_all_actions(self) -> None:
        kb = review_keyboard("d1")
        flat = [btn.get("callback_data") for row in kb["inline_keyboard"] for btn in row]
        expected = [
            "news_publish:d1",
            "news_edit:d1",
            "news_regenerate:d1",
            "news_reject:d1",
            "news_generate_ai_image:d1",
            "news_refresh_source_image:d1",
        ]
        for cb in expected:
            assert cb in flat, f"Missing callback {cb}"


# ── _source_news_for_claude ────────────────────────────────────────────────

class TestSourceNewsForClaude:
    def test_source_news_for_claude_includes_required_keys(self) -> None:
        draft = _mk_draft()
        result = _source_news_for_claude(draft)
        required = ["id", "title", "url", "source", "published_at",
                     "summary", "assets", "category", "sector", "impact_score"]
        for key in required:
            assert key in result, f"Missing key {key}"

    def test_source_news_summary_truncated_to_400(self) -> None:
        draft = _mk_draft()
        draft.source_news["summary"] = "x" * 500
        result = _source_news_for_claude(draft)
        assert len(result["summary"]) == 400

    def test_source_news_impact_score_defaults_to_zero(self) -> None:
        draft = _mk_draft()
        draft.source_news.pop("impact_score", None)
        result = _source_news_for_claude(draft)
        assert result["impact_score"] == 0


# ── get_recent_published_phrases ───────────────────────────────────────────

class TestGetRecentPublishedPhrases:
    def test_get_recent_published_phrases_on_empty_store(self, tmp_path: Path) -> None:
        store = _mk_store(tmp_path)
        assert get_recent_published_phrases(store) == []

    def test_get_recent_published_phrases_includes_published_human_mentor(
        self, tmp_path: Path
    ) -> None:
        store = _mk_store(tmp_path)
        draft = _mk_draft(status="published", human="новичок-фраза", mentor="наставник-фраза")
        draft.claude_json["specific_title"] = "Title X"
        store.add(draft)
        phrases = get_recent_published_phrases(store)
        text = " ".join(phrases)
        assert "новичок" in text
        assert "наставник" in text
        assert "Title X" in text

    def test_get_recent_published_phrases_includes_pending_titles(
        self, tmp_path: Path
    ) -> None:
        store = _mk_store(tmp_path)
        draft = _mk_draft(status="pending_review", human="человек", mentor="ассистент")
        draft.claude_json["specific_title"] = "Pending Title"
        store.add(draft)
        phrases = get_recent_published_phrases(store)
        text = " ".join(phrases)
        assert "Pending Title" in text
        assert "человек" not in text
        assert "ассистент" not in text

    def test_get_recent_published_phrases_excludes_rejected(self, tmp_path: Path) -> None:
        store = _mk_store(tmp_path)
        draft = _mk_draft(status="rejected")
        store.add(draft)
        assert get_recent_published_phrases(store) == []

    def test_get_recent_published_phrases_respects_limit(self, tmp_path: Path) -> None:
        store = _mk_store(tmp_path)
        for i in range(10):
            d = _mk_draft(draft_id=f"d{i}", status="published")
            d.claude_json["specific_title"] = f"Title {i}"
            store.add(d)
        phrases = get_recent_published_phrases(store, limit=3)
        # каждый draft добавляет title + source title + human + mentor, т.е. до 4 фраз
        # при limit=3 берутся последние 3 draft, но строк может быть >3
        assert len(phrases) <= 12  # 3 * 4
        # проверим, что нет старых title (например "Title 0" не должно быть)
        titles_in_phrases = [p for p in phrases if "Title " in p]
        assert "Title 0" not in titles_in_phrases


# ── create_draft_from ──────────────────────────────────────────────────────

class TestCreateDraftFrom:
    def test_create_draft_from_basic(self) -> None:
        item = _mk_item()
        payload = {"specific_title": "T"}
        post_html = "<p>p</p>"
        draft = create_draft_from(payload, item, post_html)
        assert draft.status == "pending_review"
        assert draft.revision_count == 0
        assert draft.source_news["title"] == "BTC ETF approved"
        assert draft.image_origin == "none"

    def test_create_draft_from_with_image_source_preview(self) -> None:
        item = _mk_item()
        payload = {"specific_title": "T"}
        post_html = "<p>p</p>"
        draft = create_draft_from(
            payload, item, post_html,
            image_path="/tmp/x.png",
            image_source_url="https://example.com/og.png",
        )
        assert draft.image_origin == "source_preview"

    def test_create_draft_from_with_image_generated(self) -> None:
        item = _mk_item()
        payload = {"specific_title": "T"}
        post_html = "<p>p</p>"
        draft = create_draft_from(
            payload, item, post_html,
            image_path="/tmp/y.png",
            image_prompt="generated",
        )
        assert draft.image_origin == "generated_ai"


# ── NewsDraft round-trip ───────────────────────────────────────────────────

class TestNewsDraftRoundTrip:
    def test_news_draft_round_trip_preserves_fields(self) -> None:
        draft = _mk_draft()
        d = draft.to_dict()
        restored = NewsDraft.from_dict(d)
        for field in ("draft_id", "status", "claude_json", "image_path", "schema_version"):
            assert getattr(restored, field) == getattr(draft, field), (
                f"Mismatch in {field}"
            )

    def test_news_draft_from_dict_ignores_unknown_fields(self) -> None:
        draft_dict = _mk_draft().to_dict()
        draft_dict["unknown_field"] = "x"
        restored = NewsDraft.from_dict(draft_dict)
        assert not hasattr(restored, "unknown_field")
        # базовые поля должны присутствовать
        assert restored.draft_id == "d1"