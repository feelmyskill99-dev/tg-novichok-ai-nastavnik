# Задача: написать tests/test_json_compat.py

## Цель

Pytest-тесты обратной совместимости JSON-drafts. После добавления новых полей
старые draft-записи (без этих полей) должны загружаться без падений и потери
данных.

Покрываемые stores:
- `news.drafts.DraftStore` (NewsDraft) — drafts с image_path, schema_version,
  image_origin, image_source_url, image_credit, image_prompt, image_model,
  image_created_at, guard_reasons.
- `author_notes.AuthorNoteStore` (AuthorNoteDraft) — rubric, claude_json,
  post_html, revision_count, owner_feedback, updated_at.
- `weekly_diary.WeeklyDiaryStore` (WeeklyDiaryDraft) — то же.

Все три используют один паттерн `from_dict()` с whitelist по
`__dataclass_fields__`. То есть: лишние поля молча игнорируются, отсутствующие
заменяются дефолтами из dataclass.

## Правила

1. **pytest** + `tmp_path` fixture. Без моков.
2. Без эмодзи, короткие имена тестов.
3. Импорты:
   - `from news.drafts import NewsDraft, DraftStore`
   - `from author_notes import AuthorNoteDraft, AuthorNoteStore`
   - `from weekly_diary import WeeklyDiaryDraft, WeeklyDiaryStore`
   - `import json`
   - `from pathlib import Path`
4. Файл — самодостаточный. В начале:
   ```python
   import sys
   from pathlib import Path
   ROOT = Path(__file__).resolve().parent.parent
   sys.path.insert(0, str(ROOT))
   ```
5. Каждый тест создаёт `tmp_path / "<name>.json"` с легаси-данными (вручную
   собранным JSON), затем создаёт store и проверяет загрузку.

## Обязательные сценарии

### NewsDraft (через DraftStore)

1. **test_news_draft_loads_legacy_v1_without_image_fields**
   Старый draft без image_path / schema_version / image_origin. Запиши JSON-массив
   с одной записью:
   ```json
   [{
     "draft_id": "abc123",
     "created_at": "2026-04-01T10:00:00+00:00",
     "status": "pending_review",
     "source_news": {"title": "t", "url": "u", "source": "CoinDesk"},
     "post_html": "<b>old</b>",
     "claude_json": {"specific_title": "T"},
     "revision_count": 0,
     "owner_feedback": [],
     "updated_at": ""
   }]
   ```
   Создай `DraftStore(path)`, вызови `list_all()`. Должна вернуться 1 запись,
   `image_path == ""`, `schema_version == "v2"` (дефолт), `image_origin == "none"`,
   `guard_reasons == []`.

2. **test_news_draft_get_by_id_works_on_legacy**
   Аналогично, но `store.get("abc123")` — не None, поля заполнены.

3. **test_news_draft_extra_fields_ignored**
   Запиши draft с лишним полем `"deprecated_field": "x"`. Загрузка не падает,
   получается NewsDraft без этого поля (по whitelist `__dataclass_fields__`).

4. **test_news_draft_corrupt_json_returns_empty**
   Запиши в файл `"not valid json{"`. `store.list_all()` возвращает `[]`,
   не падает.

5. **test_news_draft_missing_file_returns_empty**
   `tmp_path / "absent.json"` не существует. `store.list_all()` → `[]`.

6. **test_news_draft_add_update_roundtrip_preserves_new_fields**
   Создай новый `NewsDraft` через
   `NewsDraft(draft_id="x", created_at="2026-05-01T00:00:00+00:00",
   status="pending_review", source_news={}, post_html="<p>p</p>",
   claude_json={}, image_path="/tmp/img.png", schema_version="v2",
   image_origin="generated_ai")`.
   `store.add(draft)`. `store.get("x")` возвращает draft с этими полями.

### AuthorNoteDraft (через AuthorNoteStore)

7. **test_author_note_loads_legacy_minimal**
   ```json
   [{
     "draft_id": "an1",
     "created_at": "2026-04-01T10:00:00+00:00",
     "status": "pending_review",
     "rubric": "what_i_understood",
     "claude_json": {"title": "T"},
     "post_html": "<p>post</p>"
   }]
   ```
   Загрузка: 1 запись, `revision_count == 0`, `owner_feedback == []`,
   `updated_at == ""`.

8. **test_author_note_corrupt_returns_empty**
   "not json{" → `list_all() == []`.

9. **test_author_note_extra_fields_ignored**
   Лишнее поле `"foo": "bar"` → не падает, draft без foo.

### WeeklyDiaryDraft (через WeeklyDiaryStore)

10. **test_weekly_diary_loads_legacy_minimal**
    Проверь по аналогии: создай минимальный JSON, удостоверься что грузится,
    дефолты заполнены. ВАЖНО: посмотри `weekly_diary.WeeklyDiaryDraft` в коде
    из контекста — список обязательных и опциональных полей оттуда.

11. **test_weekly_diary_corrupt_returns_empty** — как выше.

## Что НЕ делать

- Не используй `Mock`/`MagicMock` — все stores чистые.
- Не вызывай `os.getenv` / `load_dotenv`.
- Не пиши `if __name__ == "__main__"` в конце.
- Не проверяй внутренние имена методов (`_load`, `_save`) — только публичный API.

## Шаблон assert для list[str]

ВАЖНО: в Python `"X" in ["Y X Z"]` это `False` (точное сравнение). Для
поиска подстроки используй `any("X" in s for s in lst)`. В этих тестах
этот паттерн НЕ нужен (нет ассертов на reasons), но имей в виду.

## Структура файла

```python
"""Backward compatibility tests for JSON draft stores."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from news.drafts import NewsDraft, DraftStore
from author_notes import AuthorNoteDraft, AuthorNoteStore
from weekly_diary import WeeklyDiaryDraft, WeeklyDiaryStore


def test_news_draft_loads_legacy_v1_without_image_fields(tmp_path):
    path = tmp_path / "news_drafts.json"
    path.write_text(json.dumps([{
        # ... минимальный legacy draft
    }]), encoding="utf-8")

    store = DraftStore(path)
    items = store.list_all()

    assert len(items) == 1
    # ... проверки дефолтов
```

Дальше — все тесты по списку выше.
