# Задача: tests/test_publish_lock_edge.py

## Цель

Дополнительное покрытие `core.publish_lock`. Базовый `tests/test_publish_idempotency.py`
уже покрывает основной CAS-flow. Здесь — граничные случаи и контракт API.

## Правила

1. pytest. Без моков (только in-memory FakeStore).
2. Без эмодзи. Импорты:
   ```python
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
   ```
3. Используй такой же `_FakeStore` + `_FakeDraft` паттерн как в
   tests/test_publish_idempotency.py, но определи их В НАЧАЛЕ файла этого теста (он самодостаточный).

## FakeStore — минимальная in-memory реализация

```python
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
        # Важно: возвращаем КОПИЮ, чтобы тестировать сценарий race
        # (модификация in-memory копии до .update не меняет store).
        return _FakeDraft(draft_id=d.draft_id, status=d.status)

    def update(self, draft: _FakeDraft) -> None:
        self._items[draft.draft_id] = _FakeDraft(
            draft_id=draft.draft_id, status=draft.status,
        )
```

## Обязательные тесты

### Константы / контракт API

1. **test_terminal_statuses_contains_publishing_published_rejected** —
   `"publishing" in TERMINAL_STATUSES`, `"published" in TERMINAL_STATUSES`,
   `"rejected" in TERMINAL_STATUSES`.

2. **test_publishing_status_constant** — `PUBLISHING_STATUS == "publishing"`.

### try_claim_for_publishing — граничные сценарии

3. **test_claim_with_custom_terminal_statuses** — `try_claim_for_publishing(
   store, "d1", terminal=["custom_done"])`. Создай draft со
   `status="custom_done"` — claim вернёт None (используется кастомный список).
   Создай draft со `status="published"` — НЕ в кастомном terminal списке →
   claim **сработает** (поменяет на "publishing"). Это проверяет что
   параметр `terminal` действительно overrides defaults.

4. **test_claim_with_empty_terminal_iterable** — `terminal=[]` (пустой
   список). Draft в **любом** статусе будет claimed (т.к. ни один статус
   не считается terminal). Создай draft со status="published" и убедись
   что claim сработал.

5. **test_claim_publishing_idempotency_under_default** — draft.status=
   "publishing" (с дефолтным terminal) → claim возвращает None (publishing
   входит в TERMINAL_STATUSES).

6. **test_claim_revised_status_not_terminal** — draft.status="revised"
   (это reviewer-flow между pending и approved). claim **сработает** —
   "revised" не в default terminal.

7. **test_claim_with_set_as_terminal** — `terminal={"published","rejected"}`
   (set вместо list). Должно работать — в коде set(terminal). Проверь и
   для frozenset.

### release_claim

8. **test_release_only_works_on_publishing_status** — draft со
   `status="published"` → `release_claim()` НЕ меняет status (метод проверяет
   `if draft.status != PUBLISHING_STATUS: return`).

9. **test_release_on_missing_draft_is_noop** — пустой store.
   `release_claim(store, "missing")` не падает, ничего не делает.

10. **test_release_custom_new_status** — claim draft → release с
    `new_status="rejected"`. После: draft.status == "rejected".

11. **test_release_default_status_is_pending_review** — claim draft →
    `release_claim(store, "d1")` без аргументов. draft.status ==
    "pending_review".

### Полный цикл

12. **test_full_cycle_claim_release_reclaim** — claim → release →
    second claim should succeed. Это сценарий «попробовать опубликовать,
    упасть, повторить».

## Что НЕ делать

- Не используй реальный `news.drafts.DraftStore` — здесь in-memory достаточно.
- Не пиши `if __name__ == "__main__"` в конце.
- НЕ путай `"X" in set_of_strings` (это ок, точное сравнение) с
  `"X" in list_of_strings`-как-substring (нужен `any()`).

## Финальный ответ

Один Python-блок ```python ... ``` готового файла. Без пояснений.
