"""Idempotency для publish-flow (этап 1.2 рефакторинга).

`try_claim_for_publishing(store, draft_id)` — атомарный compare-and-set:
    * если draft уже в terminal-статусе (published/rejected/publishing) — вернуть None
    * иначе перевести в "publishing" и вернуть обновлённый draft

Это и есть guard, который двойной клик на ✅ Опубликовать НЕ позволит превратить в два send.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.json_store import load_json, save_json
from core.publish_lock import try_claim_for_publishing


@dataclass
class _FakeDraft:
    draft_id: str
    status: str = "pending_review"
    payload: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "_FakeDraft":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class _FakeStore:
    """Минимальный store на json_store (как author/weekly/news drafts)."""

    def __init__(self, path: Path):
        self.path = path

    def _load(self) -> list[dict]:
        return load_json(self.path, default=[], expected_type=list)

    def _save(self, records: list[dict]) -> None:
        save_json(self.path, records)

    def get(self, draft_id: str) -> Optional[_FakeDraft]:
        for d in self._load():
            if d.get("draft_id") == draft_id:
                return _FakeDraft.from_dict(d)
        return None

    def add(self, draft: _FakeDraft) -> None:
        records = self._load()
        records.append(draft.to_dict())
        self._save(records)

    def update(self, draft: _FakeDraft) -> None:
        records = self._load()
        for i, d in enumerate(records):
            if d.get("draft_id") == draft.draft_id:
                records[i] = draft.to_dict()
                self._save(records)
                return
        records.append(draft.to_dict())
        self._save(records)


@pytest.fixture
def store(tmp_path: Path) -> _FakeStore:
    s = _FakeStore(tmp_path / "drafts.json")
    s.add(_FakeDraft(draft_id="d1", status="pending_review", payload="hello"))
    return s


def test_claim_pending_returns_publishing_draft(store: _FakeStore) -> None:
    claimed = try_claim_for_publishing(store, "d1")

    assert claimed is not None
    assert claimed.status == "publishing"
    # store тоже обновлён, не только in-memory копия
    assert store.get("d1").status == "publishing"


def test_second_claim_returns_none(store: _FakeStore) -> None:
    first = try_claim_for_publishing(store, "d1")
    assert first is not None

    second = try_claim_for_publishing(store, "d1")

    assert second is None
    assert store.get("d1").status == "publishing"


def test_claim_when_already_published_returns_none(store: _FakeStore) -> None:
    d = store.get("d1")
    d.status = "published"
    store.update(d)

    result = try_claim_for_publishing(store, "d1")

    assert result is None


def test_claim_when_rejected_returns_none(store: _FakeStore) -> None:
    d = store.get("d1")
    d.status = "rejected"
    store.update(d)

    result = try_claim_for_publishing(store, "d1")

    assert result is None


def test_claim_revised_draft_succeeds(store: _FakeStore) -> None:
    d = store.get("d1")
    d.status = "revised"
    store.update(d)

    result = try_claim_for_publishing(store, "d1")

    assert result is not None
    assert result.status == "publishing"


def test_claim_unknown_draft_returns_none(store: _FakeStore) -> None:
    result = try_claim_for_publishing(store, "missing")

    assert result is None


def test_release_back_to_pending_after_failure(store: _FakeStore) -> None:
    """Семантика отката: если send упал, draft возвращается в pending_review,
    чтобы владелец мог нажать ✅ повторно."""
    from core.publish_lock import release_claim

    claimed = try_claim_for_publishing(store, "d1")
    assert claimed is not None

    release_claim(store, "d1", new_status="pending_review")

    assert store.get("d1").status == "pending_review"
    # И повторный claim снова работает
    again = try_claim_for_publishing(store, "d1")
    assert again is not None
