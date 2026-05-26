import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.storage import DraftStore, TradeStore, JournalStore


class _MinimalDraftStore:
    def add(self, draft):
        pass
    def get(self, draft_id):
        return None
    def list_all(self):
        return []
    def list_pending(self):
        return []
    def update(self, draft):
        pass


class _MinimalTradeStore:
    def find(self, trade_id):
        return None
    def upsert(self, trade):
        pass
    def load(self):
        return []
    def save(self, trades):
        pass
    def pending(self):
        return []


class _MinimalJournalStore:
    def append(self, event):
        pass


class _InMemoryDraftStore:
    def __init__(self):
        self._items: dict[str, dict] = {}
    def add(self, draft):
        self._items[draft["draft_id"]] = dict(draft)
    def get(self, draft_id):
        d = self._items.get(draft_id)
        return dict(d) if d else None
    def list_all(self):
        return [dict(d) for d in self._items.values()]
    def list_pending(self):
        return [dict(d) for d in self._items.values()
                if d.get("status") in ("pending_review", "revised")]
    def update(self, draft):
        self._items[draft["draft_id"]] = dict(draft)


class _InMemoryJournal:
    def __init__(self):
        self.events: list[dict] = []
    def append(self, event):
        self.events.append(event)


def test_minimal_dict_based_draft_store_conforms():
    store = _MinimalDraftStore()
    assert isinstance(store, DraftStore)


def test_minimal_trade_store_conforms():
    store = _MinimalTradeStore()
    assert isinstance(store, TradeStore)


def test_minimal_journal_store_conforms():
    store = _MinimalJournalStore()
    assert isinstance(store, JournalStore)


def test_draft_store_missing_method_does_not_conform():
    class _MissingUpdate:
        def add(self, draft): pass
        def get(self, draft_id): return None
        def list_all(self): return []
        def list_pending(self): return []
    store = _MissingUpdate()
    assert not isinstance(store, DraftStore)


def test_trade_store_missing_pending_does_not_conform():
    class _MissingPending:
        def find(self, trade_id): return None
        def upsert(self, trade): pass
        def load(self): return []
        def save(self, trades): pass
    store = _MissingPending()
    assert not isinstance(store, TradeStore)


def test_journal_store_missing_append_does_not_conform():
    class _Empty:
        pass
    store = _Empty()
    assert not isinstance(store, JournalStore)


def test_random_class_does_not_conform_to_draft_store():
    class _Random:
        pass
    obj = _Random()
    assert not isinstance(obj, DraftStore)


def test_dict_object_does_not_conform():
    assert not isinstance({}, DraftStore)


def test_inmemory_draft_store_round_trip():
    store = _InMemoryDraftStore()
    draft1 = {"draft_id": "d1", "status": "pending_review", "content": "a"}
    draft2 = {"draft_id": "d2", "status": "pending_review", "content": "b"}
    store.add(draft1)
    store.add(draft2)
    all_drafts = store.list_all()
    assert len(all_drafts) == 2
    retrieved = store.get("d1")
    assert retrieved is not None
    assert retrieved["draft_id"] == "d1"
    # update
    draft1_updated = {"draft_id": "d1", "status": "approved", "content": "a"}
    store.update(draft1_updated)
    retrieved_updated = store.get("d1")
    assert retrieved_updated["status"] == "approved"


def test_inmemory_journal_append_preserves_order():
    journal = _InMemoryJournal()
    a = {"event": "a"}
    b = {"event": "b"}
    c = {"event": "c"}
    journal.append(a)
    journal.append(b)
    journal.append(c)
    assert journal.events == [a, b, c]


def test_protocols_are_classes():
    assert isinstance(DraftStore, type)
    assert isinstance(TradeStore, type)
    assert isinstance(JournalStore, type)


def test_runtime_checkable_decorator_present():
    store = _MinimalDraftStore()
    assert isinstance(store, DraftStore)          # no TypeError
    assert getattr(DraftStore, "_is_runtime_protocol", False) is True