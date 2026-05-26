import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.publish_lock import (
    try_claim_for_publishing,
    release_claim,
    TERMINAL_STATUSES,
    PUBLISHING_STATUS,
)


@dataclass
class _FakeDraft:
    draft_id: str
    status: str = "pending_review"

    def to_dict(self) -> dict:
        return asdict(self)


class _FakeStore:
    def __init__(self):
        self._items: dict[str, _FakeDraft] = {}

    def get(self, draft_id: str) -> Optional[_FakeDraft]:
        d = self._items.get(draft_id)
        if d is None:
            return None
        return _FakeDraft(draft_id=d.draft_id, status=d.status)

    def update(self, draft: _FakeDraft) -> None:
        self._items[draft.draft_id] = _FakeDraft(
            draft_id=draft.draft_id, status=draft.status,
        )


# ============================================================
# Константы / контракт API
# ============================================================

def test_terminal_statuses_contains_publishing_published_rejected():
    assert "publishing" in TERMINAL_STATUSES
    assert "published" in TERMINAL_STATUSES
    assert "rejected" in TERMINAL_STATUSES

def test_publishing_status_constant():
    assert PUBLISHING_STATUS == "publishing"


# ============================================================
# try_claim_for_publishing – граничные сценарии
# ============================================================

def test_claim_with_custom_terminal_statuses():
    store = _FakeStore()
    store.update(_FakeDraft(draft_id="d1", status="custom_done"))
    result = try_claim_for_publishing(store, "d1", terminal=["custom_done"])
    assert result is None
    draft = store.get("d1")
    assert draft.status == "custom_done"

    # второй draft со статусом "published", который не в кастомном списке
    store.update(_FakeDraft(draft_id="d2", status="published"))
    result = try_claim_for_publishing(store, "d2", terminal=["custom_done"])
    assert result is not None
    draft = store.get("d2")
    assert draft.status == PUBLISHING_STATUS

def test_claim_with_empty_terminal_iterable():
    store = _FakeStore()
    store.update(_FakeDraft(draft_id="d1", status="published"))
    result = try_claim_for_publishing(store, "d1", terminal=[])
    assert result is not None
    draft = store.get("d1")
    assert draft.status == PUBLISHING_STATUS

def test_claim_publishing_idempotency_under_default():
    store = _FakeStore()
    store.update(_FakeDraft(draft_id="d1", status=PUBLISHING_STATUS))
    result = try_claim_for_publishing(store, "d1")
    assert result is None
    draft = store.get("d1")
    assert draft.status == PUBLISHING_STATUS

def test_claim_revised_status_not_terminal():
    store = _FakeStore()
    store.update(_FakeDraft(draft_id="d1", status="revised"))
    result = try_claim_for_publishing(store, "d1")
    assert result is not None
    draft = store.get("d1")
    assert draft.status == PUBLISHING_STATUS

def test_claim_with_set_as_terminal():
    store = _FakeStore()
    store.update(_FakeDraft(draft_id="d1", status="published"))
    result = try_claim_for_publishing(store, "d1", terminal={"published", "rejected"})
    assert result is None
    draft = store.get("d1")
    assert draft.status == "published"

    store.update(_FakeDraft(draft_id="d2", status="pending_review"))
    result = try_claim_for_publishing(store, "d2", terminal={"published", "rejected"})
    assert result is not None
    draft = store.get("d2")
    assert draft.status == PUBLISHING_STATUS

    # проверка с frozenset
    store.update(_FakeDraft(draft_id="d3", status="rejected"))
    result = try_claim_for_publishing(store, "d3", terminal=frozenset({"published", "rejected"}))
    assert result is None
    draft = store.get("d3")
    assert draft.status == "rejected"


# ============================================================
# release_claim
# ============================================================

def test_release_only_works_on_publishing_status():
    store = _FakeStore()
    store.update(_FakeDraft(draft_id="d1", status="published"))
    release_claim(store, "d1")
    draft = store.get("d1")
    assert draft.status == "published"

def test_release_on_missing_draft_is_noop():
    store = _FakeStore()
    release_claim(store, "nonexistent")

def test_release_custom_new_status():
    store = _FakeStore()
    store.update(_FakeDraft(draft_id="d1", status="pending_review"))
    try_claim_for_publishing(store, "d1")  # -> переводит в publishing
    release_claim(store, "d1", new_status="rejected")
    draft = store.get("d1")
    assert draft.status == "rejected"

def test_release_default_status_is_pending_review():
    store = _FakeStore()
    store.update(_FakeDraft(draft_id="d1", status="pending_review"))
    try_claim_for_publishing(store, "d1")
    release_claim(store, "d1")
    draft = store.get("d1")
    assert draft.status == "pending_review"


# ============================================================
# Полный цикл
# ============================================================

def test_full_cycle_claim_release_reclaim():
    store = _FakeStore()
    store.update(_FakeDraft(draft_id="d1", status="pending_review"))
    # первый claim
    result = try_claim_for_publishing(store, "d1")
    assert result is not None
    draft = store.get("d1")
    assert draft.status == PUBLISHING_STATUS

    # release
    release_claim(store, "d1")
    draft = store.get("d1")
    assert draft.status == "pending_review"

    # повторный claim должен сработать
    result = try_claim_for_publishing(store, "d1")
    assert result is not None
    draft = store.get("d1")
    assert draft.status == PUBLISHING_STATUS