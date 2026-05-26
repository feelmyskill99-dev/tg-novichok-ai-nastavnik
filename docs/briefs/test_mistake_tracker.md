# Задача: написать tests/test_mistake_tracker.py

## Цель

Pytest-тесты для `core.mistake_tracker.MistakeTracker`. Класс — чистый
JSON-based трекер тем. Все методы синхронные, без сети, без Claude.

## Правила

1. pytest + `tmp_path` fixture. Без моков, без monkeypatch (кроме datetime — см. ниже).
2. Без эмодзи в коде/комментариях.
3. Импорты:
   ```python
   import json
   import sys
   from datetime import datetime, timezone, timedelta
   from pathlib import Path
   import pytest
   ROOT = Path(__file__).resolve().parent.parent
   sys.path.insert(0, str(ROOT))
   from core.mistake_tracker import MistakeTracker
   ```
4. Каждый тест начинает с создания **tmp_path / "themes.json"** с минимальной
   корректной структурой и опционально **tmp_path / "state.json"**. Затем
   создаёт `MistakeTracker(themes_file=str(themes_path), state_file=str(state_path))`.

## Структура файлов

**themes.json** (input для конструктора):
```json
{
  "fomo": {"title": "FOMO трейдинг"},
  "no_stop": {"title": "Торговля без стопа"},
  "overleverage": {"title": "Слишком большое плечо"}
}
```

**state.json** (опциональный input, может не существовать):
```json
{
  "log": [
    {"theme_id": "fomo", "ts": "2026-05-01T10:00:00+00:00"}
  ]
}
```

## Обязательные сценарии

### Конструктор

1. **test_init_with_existing_state** — создай themes.json и state.json,
   убедись что `tracker.themes` и `tracker.state` загрузились.

2. **test_init_without_state_file** — themes.json есть, state.json НЕ
   существует. После init: `tracker.state == {"log": []}`.

3. **test_init_missing_themes_file_raises** — themes.json не существует —
   должно бросить `FileNotFoundError` или `OSError`.

### `get_next_topic()`

4. **test_get_next_topic_returns_never_used_first** — themes: 3 темы,
   state.log имеет только запись для `"fomo"` за вчера. `get_next_topic()`
   должен вернуть title одной из НЕИСПОЛЬЗОВАННЫХ тем (`"Торговля без стопа"`
   или `"Слишком большое плечо"`) — потому что у них `age=timedelta.max`.

5. **test_get_next_topic_returns_oldest_when_all_used** — у всех 3 тем
   есть запись в log: fomo=сегодня, no_stop=неделю назад, overleverage=
   месяц назад. Возвращается `"Слишком большое плечо"` (самая старая).

6. **test_get_next_topic_uses_latest_ts_for_repeated_theme** — fomo
   использовалась 3 раза: 30 дней назад, 1 час назад, 2 дня назад. У
   no_stop одна запись за неделю назад. У overleverage одна за 14 дней назад.
   `get_next_topic()` должен вернуть **`"Слишком большое плечо"`** (14 дней,
   старше чем самая свежая fomo-запись = 1 час).

### `record_usage()`

7. **test_record_usage_appends_to_log** — `record_usage("fomo")` →
   `tracker.state["log"]` имеет +1 запись с `theme_id="fomo"` и валидным ISO `ts`.

8. **test_record_usage_persists_to_disk** — после `record_usage("no_stop")`
   читаем `state.json` напрямую через `json.load(state_path.open(...))` —
   там новая запись.

9. **test_record_usage_caps_log_at_200** — записать вручную в state 250
   записей (cycle theme_ids), затем вызвать `record_usage("fomo")`.
   После: `len(tracker.state["log"]) == 200`, и последняя запись — fomo.

### `weekly_report()`

10. **test_weekly_report_empty_log** — пустой state. Отчёт содержит
    строку `"не разбирали ошибок"` и `"Все темы актуальны."` или
    `"давно не поднимались"`-блок с никогда-не-используемыми темами.

11. **test_weekly_report_top_topics** — state с 5 записями для fomo, 2 для
    no_stop, 1 для overleverage — ВСЕ за последние 7 дней. Отчёт содержит
    `"FOMO трейдинг — 5 раз"`, `"Торговля без стопа — 2 раз"`.

12. **test_weekly_report_excludes_old_records** — state с 10 записями
    fomo, ВСЕ старше 10 дней назад. Отчёт говорит `"не разбирали ошибок"`
    в недельной секции (т.к. cutoff = 7 дней).

13. **test_weekly_report_forgotten_topics_includes_never_used** — themes
    с 3 темами; state имеет только fomo. Раздел "давно не поднимались"
    содержит title неиспользованных тем.

14. **test_weekly_report_returns_html_formatted_string** — отчёт содержит
    `"<b>"` и `"</b>"` (HTML markup для Telegram parse_mode=HTML).

## Подсказки по созданию state-данных

Чтобы получить ISO timestamp за N дней назад:
```python
ts = (datetime.now(tz=timezone.utc) - timedelta(days=N)).isoformat(timespec="seconds")
```

Запись state вручную:
```python
state_path = tmp_path / "state.json"
state_path.write_text(json.dumps({"log": [
    {"theme_id": "fomo", "ts": ts}
]}, ensure_ascii=False), encoding="utf-8")
```

## Что НЕ делать

- Не моки (включая mock_open).
- Не вызывать `os.getenv` / `load_dotenv`.
- Не пиши `if __name__ == "__main__"` в конце.
- Не используй `freezegun` или другие time-mocking либы — они не установлены.
  Просто проставляй ts на N дней назад от `datetime.now(tz=timezone.utc)`.
- НЕ используй `assert "X" in some_list_of_strings` — это точное сравнение
  элементов списка. Для проверки подстроки в `weekly_report()` (он
  возвращает СТРОКУ, не список) `"X" in report_str` корректно. Но не путай.

## Финальный ответ

Один Python-блок ```python ... ``` готового файла. Без пояснений.
