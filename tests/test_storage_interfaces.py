"""Этап 2.1: storage-интерфейсы перед SQLite.

`core.storage` определяет Protocol-интерфейсы, которым УЖЕ соответствуют все
текущие JSON-store классы. Тесты — это runtime-conformance check: existing
classes structurally implement the protocol.

Цель: SQLite-реализация в будущем сможет встать на место JSON без правки
бизнес-логики (которая работает через интерфейс).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.storage import DraftStore, TradeStore, JournalStore


def test_news_draft_store_conforms_to_draft_store():
    from news.drafts import DraftStore as NewsDraftStore

    # runtime_checkable Protocol → isinstance works на дакт-структуре
    instance = NewsDraftStore(Path("ignored.json"))
    assert isinstance(instance, DraftStore), (
        f"NewsDraftStore не соответствует DraftStore. "
        f"methods={[m for m in dir(NewsDraftStore) if not m.startswith('_')]}"
    )


def test_author_note_store_conforms():
    from author_notes import AuthorNoteStore

    instance = AuthorNoteStore(Path("ignored.json"))
    assert isinstance(instance, DraftStore)


def test_weekly_diary_store_conforms():
    from weekly_diary import WeeklyDiaryStore

    instance = WeeklyDiaryStore(Path("ignored.json"))
    assert isinstance(instance, DraftStore)


def test_confirm_trades_store_conforms_to_trade_store():
    from trading.confirm_models import ConfirmTradesStore

    instance = ConfirmTradesStore(Path("ignored.json"))
    assert isinstance(instance, TradeStore), (
        f"ConfirmTradesStore не соответствует TradeStore. "
        f"methods={[m for m in dir(ConfirmTradesStore) if not m.startswith('_')]}"
    )


def test_live_trade_journal_conforms_to_journal_store():
    from trading.confirm_models import LiveTradeJournal

    instance = LiveTradeJournal(Path("ignored.json"))
    assert isinstance(instance, JournalStore)


def test_draft_store_protocol_has_expected_methods():
    """Контракт DraftStore — синяя печать на уровне типов."""
    methods = {"add", "get", "list_all", "list_pending", "update"}
    proto_methods = {m for m in dir(DraftStore) if not m.startswith("_")}
    assert methods.issubset(proto_methods), (
        f"DraftStore protocol missing: {methods - proto_methods}"
    )


def test_trade_store_protocol_has_expected_methods():
    methods = {"find", "upsert", "load", "save", "pending"}
    proto_methods = {m for m in dir(TradeStore) if not m.startswith("_")}
    assert methods.issubset(proto_methods)


def test_journal_store_protocol_has_expected_methods():
    methods = {"append"}
    proto_methods = {m for m in dir(JournalStore) if not m.startswith("_")}
    assert methods.issubset(proto_methods)
