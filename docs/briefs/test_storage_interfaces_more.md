# Задача: tests/test_storage_interfaces_more.py

## Цель

Дополнительные тесты для `core.storage` Protocol-интерфейсов. Базовый
`tests/test_storage_interfaces.py` (8 тестов) уже проверяет что
существующие классы conform. Здесь — проверяем что Protocol работает
по контракту в **обе стороны**: и для in-memory тестовых заглушек,
и для самих интерфейсов.

## Правила

1. pytest. Без моков (только in-memory классы).
2. Без эмодзи.
3. Импорты:
   ```python
   import sys
   from dataclasses import dataclass, field
   from pathlib import Path
   from typing import Optional
   import pytest
   ROOT = Path(__file__).resolve().parent.parent
   sys.path.insert(0, str(ROOT))
   from core.storage import DraftStore, TradeStore, JournalStore
   ```

## Контракт

```python
@runtime_checkable
class DraftStore(Protocol[T]):
    def add(self, draft: T) -> None: ...
    def get(self, draft_id: str) -> Optional[T]: ...
    def list_all(self) -> list[T]: ...
    def list_pending(self) -> list[T]: ...
    def update(self, draft: T) -> None: ...

@runtime_checkable
class TradeStore(Protocol[TradeT]):
    def find(self, trade_id: str) -> Optional[TradeT]: ...
    def upsert(self, trade: TradeT) -> None: ...
    def load(self) -> list[TradeT]: ...
    def save(self, trades: list[TradeT]) -> None: ...
    def pending(self) -> list[TradeT]: ...

@runtime_checkable
class JournalStore(Protocol):
    def append(self, event: dict) -> None: ...
```

## Обязательные тесты

### Минимальный custom store conform'ит

1. **test_minimal_dict_based_draft_store_conforms** — определи в тесте
   класс `_MinimalDraftStore` с методами add/get/list_all/list_pending/update.
   `isinstance(instance, DraftStore)` → True.

2. **test_minimal_trade_store_conforms** — то же для TradeStore с
   методами find/upsert/load/save/pending.

3. **test_minimal_journal_store_conforms** — класс с одним методом `append`.
   `isinstance(instance, JournalStore)` → True.

### Не-conform'ит при отсутствующем методе

4. **test_draft_store_missing_method_does_not_conform** — класс без
   метода `update` → `isinstance(instance, DraftStore)` → False.
   (Protocol runtime_checkable должен это поймать.)

5. **test_trade_store_missing_pending_does_not_conform** — класс без
   `pending` метода → False.

6. **test_journal_store_missing_append_does_not_conform** — пустой
   класс → `isinstance(instance, JournalStore)` → False.

### Random object не conform'ит

7. **test_random_class_does_not_conform_to_draft_store** — пустой класс,
   `isinstance(instance, DraftStore)` → False.

8. **test_dict_object_does_not_conform** — обычный dict
   `isinstance({}, DraftStore)` → False.

### In-memory store как полноценная реализация

9. **test_inmemory_draft_store_round_trip** — реализуй
   `_InMemoryDraftStore` (полноценный) с `self._items: dict[str,
   draft]`. Создай 2 draft'а через add, проверь list_all=2 и
   `get("d1")` возвращает первый. Через update меняй status, проверь
   что get отдаёт обновлённое.

10. **test_inmemory_journal_append_preserves_order** —
    `_InMemoryJournal` с `self.events: list[dict]`. Append 3 события
    в порядке a/b/c. Внутренний `events` — `[a, b, c]`.

### Контракт protocol-классов как типов

11. **test_protocols_are_classes** — все три protocol должны быть
    importable как Python types: `isinstance(DraftStore, type)` True.

12. **test_runtime_checkable_decorator_present** — `@runtime_checkable`
    позволяет использовать isinstance. Это уже проверено выше косвенно.
    Дополнительно: `_ProtocolMeta` или маркер runtime_checkable
    отражается в `getattr(DraftStore, "_is_runtime_protocol", False)`
    или (для современного Python) проверь что
    `isinstance(some_object, DraftStore)` работает без `TypeError`.

## Минимальные in-memory классы

```python
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
```

## Что НЕ делать

- Не моки.
- Не пиши `if __name__ == "__main__"`.

## Финальный ответ

Один Python-блок ```python ... ``` готового файла. Без пояснений.
