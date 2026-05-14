# Задача: tests/test_content_mix_writer_more.py

## Цель

Дополнительные edge-tests для `core.content_mix_writer`. Базовый
`tests/test_content_mix_writer.py` (20 тестов) покрывает основной flow.
Здесь — boundary scenarios + большие объёмы + взаимодействие migrate+prune.

## Правила

1. pytest. Без моков.
2. Без эмодзи.
3. Импорты:
   ```python
   import json
   import sys
   from datetime import datetime, timedelta, timezone
   from pathlib import Path
   import pytest
   ROOT = Path(__file__).resolve().parent.parent
   sys.path.insert(0, str(ROOT))
   from core.content_mix_writer import (
       migrate_state, make_event, prune_log, append_event,
   )
   ```

## Helper

```python
_NOW = datetime(2026, 5, 14, 12, 0, tzinfo=timezone.utc)


def _ev_at(category: str, days_ago: float, *, published_to: str = "channel") -> dict:
    ts = (_NOW - timedelta(days=days_ago)).isoformat(timespec="seconds")
    return {
        "timestamp": ts,
        "post_type": category,
        "category": category,
        "published_to": published_to,
        "title": "",
        "source": "test",
    }
```

## Обязательные тесты

### migrate_state — детальное поведение

1. **test_migrate_when_content_mix_log_is_not_list** — `state =
   {"content_mix_log": "garbage"}` (не list, не dict).
   `migrate_state(state)` → возвращает True (создаёт пустой
   content_mix_log), потому что не isinstance list.
   ВАЖНО: в коде `if "content_mix_log" in state and
   isinstance(state["content_mix_log"], list): return False` — иначе
   идёт legacy-логика. Если legacy posts_log нет, итог:
   `state["content_mix_log"] == []`.
   Проверь: после миграции `state["content_mix_log"]` — list (пустой).

2. **test_migrate_legacy_posts_log_with_full_schema** —
   `state = {"posts_log": [{"type": "market", "ts": "2026-05-01T10:00:00+00:00"}]}`.
   После migrate: `state["content_mix_log"][0]` содержит ВСЕ ключи:
   timestamp, post_type, category, published_to, title, source.

3. **test_migrate_legacy_preserves_existing_timestamp** —
   `state = {"posts_log": [{"type": "news", "ts": "2026-04-15T08:00:00+00:00"}]}`.
   После: `state["content_mix_log"][0]["timestamp"] == "2026-04-15T08:00:00+00:00"`
   (НЕ now).

4. **test_migrate_legacy_unknown_type_becomes_other_category** —
   `posts_log = [{"type": "weird_unknown_xyz", "ts": "2026-05-01T00:00:00+00:00"}]`.
   После: `category == "other"`.

5. **test_migrate_empty_legacy_list_creates_empty_log** —
   `state = {"posts_log": []}` (пустой list). После: `state["content_mix_log"]
   == []`, `"posts_log" not in state` (удалён? Зависит от кода).
   ВНИМАНИЕ: в коде `if isinstance(legacy, list) and legacy:` — пустой
   list НЕ truthy → НЕ enters. Тогда state["content_mix_log"] создаётся
   как [] через последний `if "content_mix_log" not in state`. Проверь:
   `state["content_mix_log"] == []` и `state.get("posts_log") == []`
   (НЕ удалён, потому что не сработала ветка).

### make_event — boundary

6. **test_make_event_title_exactly_240** — title длиной ровно 240 chars.
   Результат: `len(ev["title"]) == 240`.

7. **test_make_event_title_241_truncated_to_240** — title 241 char.
   После: 240.

8. **test_make_event_with_unicode_title** — title `"Привет мир 🌍"`.
   Сохраняется как есть (не escape).

9. **test_make_event_with_none_title_returns_empty_string** —
   `make_event("news", published_to="owner", title=None, now=_NOW)`.
   `ev["title"] == ""`.

10. **test_make_event_explicit_now_used** —
    `now=datetime(2030, 1, 1, 0, 0, tzinfo=timezone.utc)`. Результат
    timestamp начинается с "2030-01-01".

### prune_log — большие объёмы

11. **test_prune_log_thousand_events_capped** — генерируй 1000
    событий за последние 5 дней. `prune_log(events, now=_NOW, days=14,
    cap=500)`. Длина == 500 (cap применяется после window-фильтра).

12. **test_prune_log_zero_days_only_now_remains** — события за
    последние 5 дней. `prune_log(events, now=_NOW, days=0)`. Length 0
    (все events в прошлом).

13. **test_prune_log_negative_cap_treated_as_empty** —
    `prune_log(events, cap=-1)`. Поведение `[-1:]` в Python = last 1
    element. Тест: вызов не падает, length ≤ 1.

14. **test_prune_log_preserves_event_order** — events с timestamps
    в возрастающем порядке. После prune: порядок сохранён.

### append_event — boundary

15. **test_append_event_to_state_with_non_list_log** —
    `state = {"content_mix_log": "garbage"}`. После append:
    `state["content_mix_log"]` — list с одним событием.

16. **test_append_event_does_not_mutate_other_state_keys** —
    `state = {"unrelated": "preserved", "other": [1, 2]}`. После append:
    оба ключа сохраняются как есть.

17. **test_append_event_with_custom_cap** —
    `state = {"content_mix_log": [_ev_at("news", days_ago=1)] * 10}`.
    `append_event(state, _ev_at(...), cap=3)`. После: ровно 3 события.

18. **test_append_event_with_custom_days_window** —
    `state = {"content_mix_log": [
        _ev_at("news", days_ago=5),
        _ev_at("news", days_ago=20),
    ]}`. `append_event(state, _ev_at(...), days=7)`. После: 2 события
    (свежее + новое; days_ago=20 выкинуто).

19. **test_append_event_preserves_new_event_in_result** —
    `append_event` всегда добавляет переданное event, даже если все
    остальные старые → отброшены.

### Combined sequences

20. **test_full_cycle_migrate_then_append** —
    `state = {"posts_log": [{"type": "market", "ts":
    "2026-05-01T00:00:00+00:00"}]}`.
    `append_event(state, make_event("news", published_to="channel",
    now=_NOW), now=_NOW)`. После:
    - `"posts_log" not in state` (мигрирован)
    - `state["content_mix_log"]` имеет 2 события (legacy + новый)
    - порядок: legacy сначала, новый последний

21. **test_append_event_multiple_times_in_sequence** —
    5 последовательных append'ов с разными post_type. После:
    `len(state["content_mix_log"]) == 5`, все 5 типов представлены.

## Что НЕ делать

- Не моки.
- Не пиши `if __name__ == "__main__"`.

## Финальный ответ

Один Python-блок ```python ... ``` готового файла. Без пояснений.
