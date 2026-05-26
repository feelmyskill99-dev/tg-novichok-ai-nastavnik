# Задача: tests/test_trade_state_advanced.py

## Цель

Дополнительные edge-tests для `core.trade_state`. Базовый
`tests/test_trade_state.py` (34 теста) покрывает основной flow.
Здесь — concurrent-like sequence scenarios + boundary cases.

## Правила

1. pytest. Без моков.
2. Без эмодзи.
3. Импорты:
   ```python
   import sys
   from datetime import datetime, timedelta, timezone
   from pathlib import Path
   import pytest
   ROOT = Path(__file__).resolve().parent.parent
   sys.path.insert(0, str(ROOT))
   from core.trade_state import (
       today_utc_iso,
       get_trade_channel_posts_today,
       increment_trade_channel_posts_today,
       set_last_trade_scan_at, set_last_trade_tick_at,
       set_gate_screenshot, get_gate_screenshot,
       remember_trade_message, lookup_trade_by_message,
   )
   ```

## Обязательные тесты

### today_utc_iso boundary

1. **test_today_utc_iso_at_midnight_utc** — `now=datetime(2026, 5, 14, 0, 0, 0, tzinfo=timezone.utc)`. Результат `"2026-05-14"` (не "2026-05-13").

2. **test_today_utc_iso_just_before_midnight** — `now=datetime(2026, 5, 14, 23, 59, 59, tzinfo=timezone.utc)`. Результат `"2026-05-14"`.

3. **test_today_utc_iso_first_day_of_year** — `now=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)`. Результат `"2026-01-01"` (с ведущими нулями).

### increment_trade_channel_posts_today — sequence

4. **test_increment_sequence_same_day** — 10 последовательных вызовов на пустом state с одним `_NOW`. Финальный `state["trade_channel_posts_today"] == 10`.

5. **test_increment_across_day_boundary** —
   `state = {}`. Вызови `increment(state, now=day1_noon)` 5 раз —
   `state["trade_channel_posts_today"] == 5`. Затем вызови
   `increment(state, now=day2_noon)` — `state["trade_channel_posts_today"] == 1`,
   `state["trade_channel_posts_date"] == "2026-05-15"`.

6. **test_get_after_increment_returns_same_value** — `increment(state, now=_NOW)`
   3 раза. `get_trade_channel_posts_today(state, now=_NOW) == 3`.

### set_last_*_at — overwrite

7. **test_set_last_scan_at_overwrites_existing** —
   `state = {"last_trade_scan_at": "old"}`. После
   `set_last_trade_scan_at(state, "new")` → `state["last_trade_scan_at"] == "new"`.

8. **test_set_last_scan_at_preserves_other_keys** —
   `state = {"foo": "bar"}`. После set: `state["foo"] == "bar"` (не затёрто).

### gate_screenshot — sequence

9. **test_multiple_set_gate_screenshot_accumulates** — добавь screenshots
   для 3 разных trade_id. `state["gate_screenshots"]` имеет 3 ключа.

10. **test_set_gate_screenshot_with_unicode_path** — путь с кириллицей
    (`"D:/Вайбкодинг/screenshot.png"`). Сохраняется и читается без потерь.

11. **test_get_gate_screenshot_with_falsy_value_in_map** —
    `state = {"gate_screenshots": {"t1": ""}}`. `get_gate_screenshot(state, "t1")`
    возвращает `""` (пустая строка), НЕ None (контракт: если ключ есть,
    отдаём value as-is).

### trade_message_index — sequence

12. **test_remember_message_then_lookup_round_trip** — после
    `remember(state, 42, "t1")` → `lookup(state, 42) == "t1"`.

13. **test_remember_message_id_str_lookup_works** — после `remember(state, 42, "t1")`:
    можно ли вызвать `lookup(state, 42)` (int) или нужна только str-ключ.
    Согласно реализации, `lookup_trade_by_message` принимает int и сам
    делает `str(message_id)`. Проверь оба пути работают одинаково.

14. **test_remember_cap_keeps_most_recent** — `cap=5`. Добавь 10 messages
    с id 100, 101, ..., 109. После: `state["trade_message_index"]` имеет
    5 ключей, содержит 105-109, не содержит 100-104.

15. **test_lookup_after_overwrite_returns_new_trade_id** —
    `remember(state, 42, "old")`, потом `remember(state, 42, "new")`.
    `lookup(state, 42) == "new"`.

16. **test_remember_with_cap_one** — `cap=1`. Add 3 messages.
    После: ровно 1 ключ — последний.

17. **test_remember_with_negative_message_id_is_noop** — `remember(state, -42, "t1")`.
    Условие в коде `if not message_id` — для -42 это False (Python truthy),
    но `str(-42)` = "-42" — это валидный ключ.
    Проверь, что НЕ noop (сохраняется как "-42").
    *ИЛИ* если код trbeats -42 как noop (зависит от реализации) —
    просто проверь поведение без падения.
    ИЗМЕНЕНИЕ: проверь что функция работает (lookup даёт результат
    либо None, без exception).

### Combined scenarios

18. **test_full_trade_state_workflow** — реалистичный сценарий:
    - state = {}
    - increment 3 times same day
    - set_last_scan_at("2026-05-14T10:00")
    - remember(42, "t1"), remember(43, "t2")
    - set_gate_screenshot("t1", "/tmp/s1.png")
    После проверяем все 4 поля присутствуют и корректны.

19. **test_independent_state_dicts_dont_share** — два разных state-dict.
    Mutations на одном не влияют на другой.

20. **test_state_dict_can_be_serialized_to_json** — после нескольких
    mutations: `json.dumps(state)` не падает (все значения JSON-сериализуемы).

## Что НЕ делать

- Не моки.
- Не пиши `if __name__ == "__main__"`.
- Не используй freezegun (нет в зависимостях) — передавай now явно.

## Финальный ответ

Один Python-блок ```python ... ``` готового файла. Без пояснений.
