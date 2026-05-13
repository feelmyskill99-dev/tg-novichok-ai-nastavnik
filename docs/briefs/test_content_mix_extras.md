# Задача: tests/test_content_mix_extras.py

## Цель

Дополнительные граничные случаи `core.content_mix.compute_mix`.
Базовый `tests/test_content_mix.py` уже покрывает основные сценарии — здесь
edge cases.

## Правила

1. pytest. Без моков. Все события — dict'ы.
2. Без эмодзи.
3. Импорты:
   ```python
   import sys
   from datetime import datetime, timezone, timedelta
   from pathlib import Path
   import pytest
   ROOT = Path(__file__).resolve().parent.parent
   sys.path.insert(0, str(ROOT))
   from core.content_mix import (
       compute_mix,
       category_for,
       CATEGORY_MAP,
       CONTENT_MIX_TARGET,
       CONTENT_MIX_WINDOW_DAYS,
       CONTENT_MIX_CHANNEL_MODE_MIN,
       CONTENT_MIX_LOW_DATA_THRESHOLD,
   )
   ```

## Базовый helper в начале файла

```python
_NOW = datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc)


def _ev(category: str, *, published_to: str = "channel", days_ago: float = 0) -> dict:
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

### Граничные cases compute_mix

1. **test_compute_mix_with_none_log_list** — `compute_mix(None, now=_NOW)`.
   Должно вернуть валидный dict с total_posts=0, recommended="education"
   (fallback low data).

2. **test_compute_mix_invalid_timestamp_skips_event** — события с
   `"timestamp": "garbage"` или `"timestamp": ""` или вообще без поля
   timestamp. compute_mix НЕ падает, такие события просто скипаются.
   Проверь: 3 валидных + 2 garbage → total_posts=3.

3. **test_compute_mix_naive_timestamp_treated_as_utc** — событие с
   `"timestamp": "2026-05-13T11:00:00"` (БЕЗ tz). compute_mix должен
   трактовать как UTC и не падать. Проверь: 3 таких события за час
   до _NOW (внутри окна) → total_posts=3.

4. **test_compute_mix_only_other_category_zero_target_total** —
   все 5 событий со `category="weird_unknown"` (не в CONTENT_MIX_TARGET).
   total_posts=5, all counts=0, shares={"market_chart":0.0, ...},
   recommended="education" (другой fallback по low data? нет — total>=3
   значит data есть; idет по under check; **все** target underrepresented
   → recommended=worst). Проверь: recommended один из 5 target-категорий,
   но НЕ "education" жёстко, а тот что underrepresented.
   ВАЖНО: тест должен проверить только что:
   - total_posts == 5
   - other_count == 5
   - all counts == 0
   - shares["market_chart"] == 0.0 (нет деления на ноль).

5. **test_compute_mix_window_boundary** — событие ровно на границе окна
   (`days_ago=CONTENT_MIX_WINDOW_DAYS - 0.01`) — внутри окна, попадает.
   Событие `days_ago=CONTENT_MIX_WINDOW_DAYS + 0.01` — снаружи, скипается.
   Проверь 2 эти события + 1 свежее → total_posts=2.

6. **test_compute_mix_now_defaults_to_datetime_now** — `compute_mix([])`
   без now. Не падает, возвращает валидный dict.

### category_for edge cases

7. **test_category_for_none** — `category_for(None)` → "other". (В коде
   `(post_type or "")` так что None станет "" и потом "other").

8. **test_category_for_all_canonical_categories_mapped** — для каждой
   ключевой категории из CATEGORY_MAP результат — одно из 5 валидных
   значений CONTENT_MIX_TARGET или "other". (Проверь для всех keys
   `CATEGORY_MAP.keys()`).

### Recommended-логика граничные cases

9. **test_compute_mix_three_events_just_threshold_for_low_data** —
   ровно `CONTENT_MIX_LOW_DATA_THRESHOLD` (3) события категории market_chart.
   total_posts=3 → НЕ срабатывает low-data fallback (т.к. условие `total <
   threshold`), а идёт по логике under/over. market_chart=100% >> 40% →
   over. Все остальные =0% << 7% delta → under. recommended — кто-то из
   under.

10. **test_compute_mix_two_events_low_data_fallback** — 2 события
    (любые). total=2 < 3 → recommended="education", reason содержит
    "мало данных".

11. **test_compute_mix_channel_mode_uses_only_channel_events** —
    4 channel-события (market_chart) + 10 owner-событий (news). Mode
    переключается на "channel" (≥3 channel), total_posts=4. counts["news"]=0.
    recommended — что-то из under (news/etc).

12. **test_compute_mix_result_target_is_independent_copy** — мутация
    `result["target"]["market_chart"] = 999` НЕ влияет на следующий
    `compute_mix()` (target возвращается как `dict(CONTENT_MIX_TARGET)`).

## Что НЕ делать

- Не моки.
- Не `time-machine`/`freezegun` — передавай `now=_NOW` явно.
- Не пиши `if __name__ == "__main__"` в конце.

## Финальный ответ

Один Python-блок ```python ... ``` готового файла. Без пояснений.
