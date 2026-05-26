"""Storage-интерфейсы перед SQLite-миграцией (этап 2.1).

Описывает `typing.Protocol` для каждого типа store. Существующие JSON-классы
СТРУКТУРНО соответствуют этим протоколам без наследования — `@runtime_checkable`
позволяет `isinstance(x, DraftStore)` работать на duck-типе.

Цель: бизнес-логика может принимать `DraftStore` (Protocol), а конкретная
реализация (JSON сегодня, SQLite завтра) свободно меняется.

Дженерики:
- `DraftStore[T]` — T это конкретный draft-dataclass (NewsDraft / AuthorNoteDraft / ...).
- `TradeStore[T]` — T это ConfirmTrade.

Протокол НЕ требует `__init__` — реализации сами решают, как создаются.
"""
from __future__ import annotations

from typing import Iterable, Optional, Protocol, TypeVar, runtime_checkable

T = TypeVar("T")
TradeT = TypeVar("TradeT")


@runtime_checkable
class DraftStore(Protocol[T]):
    """Хранилище review-drafts (news/author_notes/weekly_diary).

    Контракт совпадает с текущими JSON-реализациями: load → mutate → save
    под межпроцессным lock (через core.json_store).
    """

    def add(self, draft: T) -> None: ...

    def get(self, draft_id: str) -> Optional[T]: ...

    def list_all(self) -> list[T]: ...

    def list_pending(self) -> list[T]: ...

    def update(self, draft: T) -> None: ...


@runtime_checkable
class TradeStore(Protocol[TradeT]):
    """Хранилище ConfirmTrade / LiveTrade — статусная машина сделок."""

    def find(self, trade_id: str) -> Optional[TradeT]: ...

    def upsert(self, trade: TradeT) -> None: ...

    def load(self) -> list[TradeT]: ...

    def save(self, trades: list[TradeT]) -> None: ...

    def pending(self) -> list[TradeT]: ...


@runtime_checkable
class JournalStore(Protocol):
    """Append-only журнал событий (LiveTradeJournal / прочие audit-логи).

    Минимальный контракт — только `append`. Конкретные реализации могут
    добавлять удобные helpers (например, `log_trade_event`), но они не
    являются частью интерфейса.
    """

    def append(self, event: dict) -> None: ...
