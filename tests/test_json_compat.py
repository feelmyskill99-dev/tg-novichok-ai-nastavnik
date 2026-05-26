"""Backward compatibility tests for JSON draft stores."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from news.drafts import NewsDraft, DraftStore
from author_notes import AuthorNoteDraft, AuthorNoteStore
from weekly_diary import WeeklyDiaryDraft, WeeklyDiaryStore


# ── NewsDraft (DraftStore) ────────────────────────────────────────────────────

def test_news_draft_loads_legacy_v1_without_image_fields(tmp_path):
    path = tmp_path / "news_drafts.json"
    data = [{
        "draft_id": "abc123",
        "created_at": "2026-04-01T10:00:00+00:00",
        "status": "pending_review",
        "source_news": {"title": "t", "url": "u", "source": "CoinDesk"},
        "post_html": "<b>old</b>",
        "claude_json": {"specific_title": "T"},
        "revision_count": 0,
        "owner_feedback": [],
        "updated_at": ""
    }]
    path.write_text(json.dumps(data), encoding="utf-8")

    store = DraftStore(path)
    items = store.list_all()

    assert len(items) == 1
    draft = items[0]
    assert draft.image_path == ""
    assert draft.schema_version == "v2"
    assert draft.image_origin == "none"
    assert draft.guard_reasons == []


def test_news_draft_get_by_id_works_on_legacy(tmp_path):
    path = tmp_path / "news_drafts.json"
    data = [{
        "draft_id": "abc123",
        "created_at": "2026-04-01T10:00:00+00:00",
        "status": "pending_review",
        "source_news": {"title": "t", "url": "u", "source": "CoinDesk"},
        "post_html": "<b>old</b>",
        "claude_json": {"specific_title": "T"},
        "revision_count": 0,
        "owner_feedback": [],
        "updated_at": ""
    }]
    path.write_text(json.dumps(data), encoding="utf-8")

    store = DraftStore(path)
    draft = store.get("abc123")

    assert draft is not None
    assert draft.draft_id == "abc123"
    assert draft.image_path == ""


def test_news_draft_extra_fields_ignored(tmp_path):
    path = tmp_path / "news_drafts.json"
    data = [{
        "draft_id": "abc123",
        "created_at": "2026-04-01T10:00:00+00:00",
        "status": "pending_review",
        "source_news": {"title": "t", "url": "u", "source": "CoinDesk"},
        "post_html": "<b>old</b>",
        "claude_json": {"specific_title": "T"},
        "revision_count": 0,
        "owner_feedback": [],
        "updated_at": "",
        "deprecated_field": "x"
    }]
    path.write_text(json.dumps(data), encoding="utf-8")

    store = DraftStore(path)
    items = store.list_all()

    assert len(items) == 1
    draft = items[0]
    assert draft.draft_id == "abc123"
    assert not hasattr(draft, "deprecated_field")


def test_news_draft_corrupt_json_returns_empty(tmp_path):
    path = tmp_path / "news_drafts.json"
    path.write_text("not valid json{", encoding="utf-8")

    store = DraftStore(path)
    items = store.list_all()

    assert items == []


def test_news_draft_missing_file_returns_empty(tmp_path):
    path = tmp_path / "absent.json"
    store = DraftStore(path)
    items = store.list_all()

    assert items == []


def test_news_draft_add_update_roundtrip_preserves_new_fields(tmp_path):
    path = tmp_path / "news_drafts.json"
    store = DraftStore(path)

    draft = NewsDraft(
        draft_id="x",
        created_at="2026-05-01T00:00:00+00:00",
        status="pending_review",
        source_news={},
        post_html="<p>p</p>",
        claude_json={},
        image_path="/tmp/img.png",
        schema_version="v2",
        image_origin="generated_ai"
    )
    store.add(draft)

    loaded = store.get("x")
    assert loaded is not None
    assert loaded.image_path == "/tmp/img.png"
    assert loaded.schema_version == "v2"
    assert loaded.image_origin == "generated_ai"
    assert loaded.image_source_url == ""
    assert loaded.image_credit == ""
    assert loaded.image_prompt == ""
    assert loaded.image_model == ""
    assert loaded.image_created_at == ""
    assert loaded.guard_reasons == []


# ── AuthorNoteDraft (AuthorNoteStore) ─────────────────────────────────────────

def test_author_note_loads_legacy_minimal(tmp_path):
    path = tmp_path / "author_notes.json"
    data = [{
        "draft_id": "an1",
        "created_at": "2026-04-01T10:00:00+00:00",
        "status": "pending_review",
        "rubric": "what_i_understood",
        "claude_json": {"title": "T"},
        "post_html": "<p>post</p>"
    }]
    path.write_text(json.dumps(data), encoding="utf-8")

    store = AuthorNoteStore(path)
    items = store.list_all()

    assert len(items) == 1
    draft = items[0]
    assert draft.revision_count == 0
    assert draft.owner_feedback == []
    assert draft.updated_at == ""


def test_author_note_corrupt_returns_empty(tmp_path):
    path = tmp_path / "author_notes.json"
    path.write_text("not json{", encoding="utf-8")

    store = AuthorNoteStore(path)
    items = store.list_all()

    assert items == []


def test_author_note_extra_fields_ignored(tmp_path):
    path = tmp_path / "author_notes.json"
    data = [{
        "draft_id": "an1",
        "created_at": "2026-04-01T10:00:00+00:00",
        "status": "pending_review",
        "rubric": "what_i_understood",
        "claude_json": {"title": "T"},
        "post_html": "<p>post</p>",
        "foo": "bar"
    }]
    path.write_text(json.dumps(data), encoding="utf-8")

    store = AuthorNoteStore(path)
    items = store.list_all()

    assert len(items) == 1
    assert not hasattr(items[0], "foo")


# ── WeeklyDiaryDraft (WeeklyDiaryStore) ───────────────────────────────────────

def test_weekly_diary_loads_legacy_minimal(tmp_path):
    path = tmp_path / "weekly_diary.json"
    data = [{
        "draft_id": "wd1",
        "created_at": "2026-04-01T10:00:00+00:00",
        "status": "pending_review",
        "week_post_count": 5,
        "claude_json": {"title": "Week"},
        "post_html": "<p>week review</p>"
    }]
    path.write_text(json.dumps(data), encoding="utf-8")

    store = WeeklyDiaryStore(path)
    items = store.list_all()

    assert len(items) == 1
    draft = items[0]
    assert draft.revision_count == 0
    assert draft.owner_feedback == []
    assert draft.updated_at == ""


def test_weekly_diary_corrupt_returns_empty(tmp_path):
    path = tmp_path / "weekly_diary.json"
    path.write_text("not json{", encoding="utf-8")

    store = WeeklyDiaryStore(path)
    items = store.list_all()

    assert items == []