# Задача: tests/test_news_drafts_helpers.py

## Цель

Pytest-тесты для helper-функций из `news.drafts`, которые НЕ требуют
Claude/сети:
- `_make_draft_id(item)` — детерминированный 16-char hex
- `review_keyboard(draft_id)` — построение inline keyboard dict
- `_source_news_for_claude(draft)` — подготовка dict для Claude из draft
- `get_recent_published_phrases(store, limit)` — сбор anti-repetition фраз
- `create_draft_from(...)` — фабричный метод
- `NewsDraft.to_dict() / from_dict()` — round-trip

## Правила

1. pytest + `tmp_path`. Без моков.
2. Без эмодзи в коде/комментариях.
3. Импорты:
   ```python
   import json
   import sys
   from datetime import datetime, timezone
   from pathlib import Path
   import pytest
   ROOT = Path(__file__).resolve().parent.parent
   sys.path.insert(0, str(ROOT))
   from news.drafts import (
       NewsDraft, DraftStore,
       _make_draft_id, _source_news_for_claude,
       review_keyboard, get_recent_published_phrases,
       create_draft_from, MAX_DRAFTS,
   )
   from news.models import NewsItem
   ```

## Helper для NewsItem

```python
def _mk_item(item_id: str = "i1", title: str = "BTC ETF approved",
             source: str = "CoinDesk") -> NewsItem:
    return NewsItem(
        id=item_id,
        title=title,
        url=f"https://example.com/{item_id}",
        source=source,
        published_at="2026-05-14T10:00:00+00:00",
        summary="Brief summary",
        assets=["BTC"],
        category="etf_institutional",
        sector="regulation_etf_institutional",
        impact_score=85.0,
    )
```

## Helper для NewsDraft

```python
def _mk_draft(draft_id: str = "d1", status: str = "pending_review",
              human: str = "тут думает новичок",
              mentor: str = "тут вмешивается AI-наставник") -> NewsDraft:
    return NewsDraft(
        draft_id=draft_id,
        created_at="2026-05-14T10:00:00+00:00",
        status=status,
        source_news={
            "id": draft_id, "title": "ETF approved",
            "url": "https://example.com/", "source": "CoinDesk",
            "published_at": "2026-05-14T09:00:00+00:00",
            "summary": "summary", "assets": ["BTC"],
            "category": "etf_institutional",
            "sector": "regulation_etf_institutional",
            "impact_score": 85.0,
        },
        post_html="<b>post</b>",
        claude_json={
            "specific_title": "ETF approved by SEC",
            "human_part": human,
            "mentor_part": mentor,
        },
    )
```

## Обязательные тесты

### `_make_draft_id(item)`

1. **test_make_draft_id_returns_16_hex** — `_make_draft_id(item)` —
   строка длиной 16 из hex-символов (`[0-9a-f]`).

2. **test_make_draft_id_includes_item_id_seed** — два разных item.id
   дают разные draft_id (потому что seed `f"{item.id}|{datetime.now}"`).

3. **test_make_draft_id_changes_with_time** — два вызова подряд
   с одним и тем же item обычно дают разные draft_id (т.к. datetime
   меняется). Но если совпали — не падаем; делаем что-то типа
   `assert id1 == id2 or id1 != id2` (тавтология, но проверяет
   что функция возвращает строку и работает).
   ПРАВИЛЬНЕЕ: проверь что функция возвращает строку длиной 16
   при многократных вызовах.

### `review_keyboard(draft_id)`

4. **test_review_keyboard_structure** — `kb = review_keyboard("d1")`.
   Проверь: `kb` — dict с ключом `"inline_keyboard"`, значение —
   list-of-lists.

5. **test_review_keyboard_includes_publish_callback** — найти кнопку
   с `callback_data == "news_publish:d1"`. Проверка через flat-scan
   всех кнопок.

6. **test_review_keyboard_includes_all_actions** — должны быть
   callbacks для всех: `news_publish`, `news_edit`, `news_regenerate`,
   `news_reject`, `news_generate_ai_image`, `news_refresh_source_image`.
   Все с suffix `:d1`.

### `_source_news_for_claude(draft)`

7. **test_source_news_for_claude_includes_required_keys** — для draft
   с заполненным source_news — результат содержит ключи: `id, title,
   url, source, published_at, summary, assets, category, sector,
   impact_score`.

8. **test_source_news_summary_truncated_to_400** — `source_news.summary =
   "x" * 500`. Результат: `result["summary"]` имеет длину 400.

9. **test_source_news_impact_score_defaults_to_zero** — `source_news`
   без `impact_score` ключа. Результат: `result["impact_score"] == 0`.

### `get_recent_published_phrases(store, limit)`

10. **test_get_recent_published_phrases_on_empty_store** — пустой
    store → `[]`.

11. **test_get_recent_published_phrases_includes_published_human_mentor** —
    добавь в store draft со `status="published"` и `claude_json={
    "specific_title": "Title X", "human_part": "новичок-фраза",
    "mentor_part": "наставник-фраза"}`. Результат содержит строки с
    `"новичок"` (substring) и `"наставник"` (substring) — и
    `specific_title`.

12. **test_get_recent_published_phrases_includes_pending_titles** —
    draft со `status="pending_review"` — только title попадает в
    результат (human/mentor НЕ берутся, потому что pending — ещё не
    финал). Проверь: title есть, human-фразы НЕТ.

13. **test_get_recent_published_phrases_excludes_rejected** — draft
    со `status="rejected"` НЕ должен попасть в результат.

14. **test_get_recent_published_phrases_respects_limit** — добавь 10
    published drafts. Вызови с `limit=3`. Должно быть ≤ 3 drafts
    учтено (но строк в результате может быть больше — на каждый draft
    несколько фраз).

### `create_draft_from(...)`

15. **test_create_draft_from_basic** — `item = _mk_item()`,
    `payload = {"specific_title": "T"}`, `post_html="<p>p</p>"`.
    Результат: NewsDraft со `status="pending_review"`, `revision_count=0`,
    `source_news.title == "BTC ETF approved"`, `image_origin == "none"`.

16. **test_create_draft_from_with_image_source_preview** —
    `image_path="/tmp/x.png"`, `image_source_url="https://example.com/og.png"`.
    Результат: `image_origin == "source_preview"`.

17. **test_create_draft_from_with_image_generated** — `image_path=...`,
    `image_prompt="generated"` (без image_source_url). Результат:
    `image_origin == "generated_ai"`.

### `NewsDraft.to_dict/from_dict` round-trip

18. **test_news_draft_round_trip_preserves_fields** — `_mk_draft()` →
    `to_dict()` → `NewsDraft.from_dict(d)` → equality по всем полям
    (draft_id, status, claude_json, image_path, schema_version).

19. **test_news_draft_from_dict_ignores_unknown_fields** — dict с
    лишним полем `"unknown_field": "x"` → from_dict не падает,
    результат — валидный NewsDraft без unknown_field.

## Что НЕ делать

- Не моки Claude/Anthropic.
- Не тестируй `regenerate_payload`/`revise_payload` (они дёргают Claude).
- Не пиши `if __name__ == "__main__"`.

## Финальный ответ

Один Python-блок ```python ... ``` готового файла. Без пояснений.
