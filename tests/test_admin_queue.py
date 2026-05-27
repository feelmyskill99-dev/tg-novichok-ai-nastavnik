"""Тесты для bulk-review очереди админки (admin_panel.py).

Стиль: test_admin_security.py.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _reload_admin(monkeypatch: pytest.MonkeyPatch, **env: str):
    """Перезагружает admin_panel с заданными env-переменными."""
    monkeypatch.setenv("TELEGRAM_TOKEN", env.get("TELEGRAM_TOKEN", "test:token"))
    monkeypatch.setenv("OWNER_CHAT_ID", env.get("OWNER_CHAT_ID", "123"))
    monkeypatch.setenv("CHANNEL_ID", env.get("CHANNEL_ID", "@test"))
    if "ADMIN_PASSWORD" in env:
        monkeypatch.setenv("ADMIN_PASSWORD", env["ADMIN_PASSWORD"])
    else:
        monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("ADMIN_USERNAME", env.get("ADMIN_USERNAME", "admin"))

    import dotenv as _dotenv
    monkeypatch.setattr(_dotenv, "load_dotenv", lambda *a, **kw: True)

    sys.modules.pop("admin_panel", None)
    import importlib
    return importlib.import_module("admin_panel")


def _extract_csrf(html_text: str) -> str:
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', html_text)
    assert m, "CSRF token not found in page"
    return m.group(1)


# ---- минимальные дикты для драфтов ----

NEWS_DRAFT = {
    "draft_id": "abc1",
    "created_at": "2026-05-27T10:00:00+00:00",
    "status": "pending_review",
    "source_news": {
        "title": "BTC pumps",
        "source": "Bloomberg",
        "sector": "ai_crypto",
        "impact_score": 85,
        "url": "",
        "published_at": "",
        "summary": "",
        "assets": [],
        "category": "other",
        "id": "x",
    },
    "post_html": "<b>hi</b>",
    "claude_json": {"specific_title": "BTC pumps"},
    "revision_count": 0,
    "owner_feedback": [],
    "updated_at": "",
    "image_path": "",
    "guard_reasons": [],
    "schema_version": "v2",
    "image_origin": "none",
    "image_source_url": "",
    "image_credit": "",
    "image_prompt": "",
    "image_model": "",
    "image_created_at": "",
}

NOTE_DRAFT = {
    "draft_id": "n1",
    "created_at": "2026-05-27T10:00:00+00:00",
    "status": "pending_review",
    "rubric": "what_i_understood",
    "claude_json": {"body": "today I learned about FOMO"},
    "post_html": "<b>note</b>",
    "revision_count": 0,
    "owner_feedback": [],
    "updated_at": "",
}


# ---------------------------------------------------------------

def test_queue_requires_auth(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """GET /admin/queue без auth → 401."""
    from fastapi.testclient import TestClient

    mod = _reload_admin(monkeypatch, ADMIN_PASSWORD="s3cret!Strong#42")
    monkeypatch.setattr(mod, "NEWS_DRAFTS_FILE", tmp_path / "news_drafts.json")
    monkeypatch.setattr(mod, "AUTHOR_NOTES_FILE", tmp_path / "author_notes_drafts.json")
    client = TestClient(mod.app)

    resp = client.get("/admin/queue")
    assert resp.status_code == 401


def test_queue_renders_pending_news_and_notes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Проверяет, что страница отображает только pending, сортировку по impact и счётчик."""
    from fastapi.testclient import TestClient

    mod = _reload_admin(monkeypatch, ADMIN_PASSWORD="s3cret!Strong#42")
    news_file = tmp_path / "news_drafts.json"
    notes_file = tmp_path / "author_notes_drafts.json"
    monkeypatch.setattr(mod, "NEWS_DRAFTS_FILE", news_file)
    monkeypatch.setattr(mod, "AUTHOR_NOTES_FILE", notes_file)

    # news pending с разными impact
    n1 = dict(NEWS_DRAFT, draft_id="n1", source_news=dict(NEWS_DRAFT["source_news"], impact_score=50))
    n2 = dict(NEWS_DRAFT, draft_id="n2", source_news=dict(NEWS_DRAFT["source_news"], impact_score=90))
    n3 = dict(NEWS_DRAFT, draft_id="n3", status="published")
    # author note pending
    note1 = dict(NOTE_DRAFT, draft_id="an1")

    news_file.write_text(json.dumps([n1, n2, n3], ensure_ascii=False), encoding="utf-8")
    notes_file.write_text(json.dumps([note1], ensure_ascii=False), encoding="utf-8")

    client = TestClient(mod.app)
    resp = client.get("/admin/queue", auth=("admin", "s3cret!Strong#42"))
    assert resp.status_code == 200
    html = resp.text

    # Все pending draft_id видны
    assert "n1" in html
    assert "n2" in html
    assert "an1" in html
    # Published не должен быть
    assert "n3" not in html
    # Счётчик news pending (2)
    assert "News pending (2)" in html
    # Порядок сортировки: n2 (impact 90) должен быть выше n1 (50)
    pos_n2 = html.index("n2")
    pos_n1 = html.index("n1")
    assert pos_n2 < pos_n1, "News должны быть отсортированы по impact desc"


def test_queue_reject_news_changes_status(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from fastapi.testclient import TestClient

    mod = _reload_admin(monkeypatch, ADMIN_PASSWORD="s3cret!Strong#42")
    news_file = tmp_path / "news_drafts.json"
    notes_file = tmp_path / "author_notes_drafts.json"
    monkeypatch.setattr(mod, "NEWS_DRAFTS_FILE", news_file)
    monkeypatch.setattr(mod, "AUTHOR_NOTES_FILE", notes_file)

    draft = dict(NEWS_DRAFT, draft_id="reject_news")
    news_file.write_text(json.dumps([draft], ensure_ascii=False), encoding="utf-8")

    client = TestClient(mod.app)
    # Получаем CSRF
    get_resp = client.get("/admin/queue", auth=("admin", "s3cret!Strong#42"))
    assert get_resp.status_code == 200
    csrf = _extract_csrf(get_resp.text)

    post_resp = client.post(
        "/admin/queue/reject",
        data={"kind": "news", "draft_id": "reject_news", "csrf_token": csrf},
        auth=("admin", "s3cret!Strong#42"),
        cookies=get_resp.cookies,
    )
    assert post_resp.status_code == 200
    data = post_resp.json()
    assert data["status"] == "ok"

    # Проверяем, что статус изменился
    stored = json.loads(news_file.read_text(encoding="utf-8"))
    assert stored[0]["status"] == "rejected"


def test_queue_reject_author_note_changes_status(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from fastapi.testclient import TestClient

    mod = _reload_admin(monkeypatch, ADMIN_PASSWORD="s3cret!Strong#42")
    news_file = tmp_path / "news_drafts.json"
    notes_file = tmp_path / "author_notes_drafts.json"
    monkeypatch.setattr(mod, "NEWS_DRAFTS_FILE", news_file)
    monkeypatch.setattr(mod, "AUTHOR_NOTES_FILE", notes_file)

    draft = dict(NOTE_DRAFT, draft_id="reject_note")
    notes_file.write_text(json.dumps([draft], ensure_ascii=False), encoding="utf-8")

    client = TestClient(mod.app)
    get_resp = client.get("/admin/queue", auth=("admin", "s3cret!Strong#42"))
    csrf = _extract_csrf(get_resp.text)

    post_resp = client.post(
        "/admin/queue/reject",
        data={"kind": "author_note", "draft_id": "reject_note", "csrf_token": csrf},
        auth=("admin", "s3cret!Strong#42"),
        cookies=get_resp.cookies,
    )
    assert post_resp.status_code == 200
    assert post_resp.json()["status"] == "ok"

    stored = json.loads(notes_file.read_text(encoding="utf-8"))
    assert stored[0]["status"] == "rejected"


def test_queue_reject_unknown_kind(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from fastapi.testclient import TestClient

    mod = _reload_admin(monkeypatch, ADMIN_PASSWORD="s3cret!Strong#42")
    news_file = tmp_path / "news_drafts.json"
    notes_file = tmp_path / "author_notes_drafts.json"
    monkeypatch.setattr(mod, "NEWS_DRAFTS_FILE", news_file)
    monkeypatch.setattr(mod, "AUTHOR_NOTES_FILE", notes_file)

    news_file.write_text("[]")
    notes_file.write_text("[]")

    client = TestClient(mod.app)
    get_resp = client.get("/admin/queue", auth=("admin", "s3cret!Strong#42"))
    csrf = _extract_csrf(get_resp.text)

    post_resp = client.post(
        "/admin/queue/reject",
        data={"kind": "dogfood", "draft_id": "x", "csrf_token": csrf},
        auth=("admin", "s3cret!Strong#42"),
        cookies=get_resp.cookies,
    )
    assert post_resp.status_code == 200
    data = post_resp.json()
    assert data["status"] == "error"
    assert "unknown kind" in data["detail"]


def test_queue_reject_missing_draft(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from fastapi.testclient import TestClient

    mod = _reload_admin(monkeypatch, ADMIN_PASSWORD="s3cret!Strong#42")
    news_file = tmp_path / "news_drafts.json"
    notes_file = tmp_path / "author_notes_drafts.json"
    monkeypatch.setattr(mod, "NEWS_DRAFTS_FILE", news_file)
    monkeypatch.setattr(mod, "AUTHOR_NOTES_FILE", notes_file)

    news_file.write_text("[]")
    notes_file.write_text("[]")

    client = TestClient(mod.app)
    get_resp = client.get("/admin/queue", auth=("admin", "s3cret!Strong#42"))
    csrf = _extract_csrf(get_resp.text)

    post_resp = client.post(
        "/admin/queue/reject",
        data={"kind": "news", "draft_id": "ghost", "csrf_token": csrf},
        auth=("admin", "s3cret!Strong#42"),
        cookies=get_resp.cookies,
    )
    assert post_resp.status_code == 200
    data = post_resp.json()
    assert data["status"] == "error"
    assert "not found or not pending" in data["detail"]


def test_queue_reject_already_published(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from fastapi.testclient import TestClient

    mod = _reload_admin(monkeypatch, ADMIN_PASSWORD="s3cret!Strong#42")
    news_file = tmp_path / "news_drafts.json"
    notes_file = tmp_path / "author_notes_drafts.json"
    monkeypatch.setattr(mod, "NEWS_DRAFTS_FILE", news_file)
    monkeypatch.setattr(mod, "AUTHOR_NOTES_FILE", notes_file)

    draft = dict(NEWS_DRAFT, draft_id="pub", status="published")
    news_file.write_text(json.dumps([draft], ensure_ascii=False), encoding="utf-8")

    client = TestClient(mod.app)
    get_resp = client.get("/admin/queue", auth=("admin", "s3cret!Strong#42"))
    csrf = _extract_csrf(get_resp.text)

    post_resp = client.post(
        "/admin/queue/reject",
        data={"kind": "news", "draft_id": "pub", "csrf_token": csrf},
        auth=("admin", "s3cret!Strong#42"),
        cookies=get_resp.cookies,
    )
    assert post_resp.status_code == 200
    data = post_resp.json()
    assert data["status"] == "error"
    assert "not found or not pending" in data["detail"]

    # Статус не изменился
    stored = json.loads(news_file.read_text(encoding="utf-8"))
    assert stored[0]["status"] == "published"


def test_queue_reject_csrf_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from fastapi.testclient import TestClient

    mod = _reload_admin(monkeypatch, ADMIN_PASSWORD="s3cret!Strong#42")
    news_file = tmp_path / "news_drafts.json"
    notes_file = tmp_path / "author_notes_drafts.json"
    monkeypatch.setattr(mod, "NEWS_DRAFTS_FILE", news_file)
    monkeypatch.setattr(mod, "AUTHOR_NOTES_FILE", notes_file)

    news_file.write_text("[]")

    client = TestClient(mod.app)
    get_resp = client.get("/admin/queue", auth=("admin", "s3cret!Strong#42"))

    post_resp = client.post(
        "/admin/queue/reject",
        data={"kind": "news", "draft_id": "x"},  # No csrf_token
        auth=("admin", "s3cret!Strong#42"),
        cookies=get_resp.cookies,
    )
    assert post_resp.status_code == 403


def test_queue_purge_older_than_threshold(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from fastapi.testclient import TestClient
    from datetime import datetime, timezone, timedelta

    mod = _reload_admin(monkeypatch, ADMIN_PASSWORD="s3cret!Strong#42")
    news_file = tmp_path / "news_drafts.json"
    notes_file = tmp_path / "author_notes_drafts.json"
    monkeypatch.setattr(mod, "NEWS_DRAFTS_FILE", news_file)
    monkeypatch.setattr(mod, "AUTHOR_NOTES_FILE", notes_file)

    now = datetime.now(tz=timezone.utc)
    today = now.isoformat()
    old_day = (now - timedelta(days=10)).isoformat()

    n1 = dict(NEWS_DRAFT, draft_id="today_news", created_at=today, status="pending_review")
    n2 = dict(NEWS_DRAFT, draft_id="old_news", created_at=old_day, status="pending_review")
    a1 = dict(NOTE_DRAFT, draft_id="old_note", created_at=old_day, status="pending_review")

    news_file.write_text(json.dumps([n1, n2], ensure_ascii=False), encoding="utf-8")
    notes_file.write_text(json.dumps([a1], ensure_ascii=False), encoding="utf-8")

    client = TestClient(mod.app)
    get_resp = client.get("/admin/queue", auth=("admin", "s3cret!Strong#42"))
    csrf = _extract_csrf(get_resp.text)

    post_resp = client.post(
        "/admin/queue/purge_older_than",
        data={"days": "3", "csrf_token": csrf},
        auth=("admin", "s3cret!Strong#42"),
        cookies=get_resp.cookies,
    )
    assert post_resp.status_code == 200
    data = post_resp.json()
    assert data["status"] == "ok"
    assert data["news"] == 1
    assert data["author_notes"] == 1

    # Проверяем файлы
    news_stored = json.loads(news_file.read_text(encoding="utf-8"))
    notes_stored = json.loads(notes_file.read_text(encoding="utf-8"))

    news_by_id = {d["draft_id"]: d for d in news_stored}
    assert news_by_id["today_news"]["status"] == "pending_review"
    assert news_by_id["old_news"]["status"] == "rejected"

    notes_by_id = {d["draft_id"]: d for d in notes_stored}
    assert notes_by_id["old_note"]["status"] == "rejected"


def test_queue_purge_invalid_days(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from fastapi.testclient import TestClient

    mod = _reload_admin(monkeypatch, ADMIN_PASSWORD="s3cret!Strong#42")
    news_file = tmp_path / "news_drafts.json"
    notes_file = tmp_path / "author_notes_drafts.json"
    monkeypatch.setattr(mod, "NEWS_DRAFTS_FILE", news_file)
    monkeypatch.setattr(mod, "AUTHOR_NOTES_FILE", notes_file)

    news_file.write_text("[]")
    notes_file.write_text("[]")

    client = TestClient(mod.app)
    get_resp = client.get("/admin/queue", auth=("admin", "s3cret!Strong#42"))
    csrf = _extract_csrf(get_resp.text)

    for days in ("0", "500"):
        post_resp = client.post(
            "/admin/queue/purge_older_than",
            data={"days": days, "csrf_token": csrf},
            auth=("admin", "s3cret!Strong#42"),
            cookies=get_resp.cookies,
        )
        assert post_resp.status_code == 200
        data = post_resp.json()
        assert data["status"] == "error"
        assert "days must be 1..365" in data["detail"]