# Задача: tests/test_admin_queue.py

Написать `pytest`-тесты для нового bulk-review модуля админки. Целевой файл:
`tests/test_admin_queue.py`. Стилистический ориентир (формат TestClient,
monkeypatch, перезагрузка модуля) — `tests/test_admin_security.py`. Используй
его как шаблон: тот же `_reload_admin(monkeypatch, **env)` helper.

## Что тестируем

Новые endpoints в `admin_panel.py`:

1. **GET /admin/queue** — HTML-страница со списком pending news_drafts и
   pending author_notes_drafts.
2. **POST /admin/queue/reject** — поля формы: `kind` ("news" | "author_note"),
   `draft_id`, `csrf_token`. Меняет status pending черновика на "rejected".
3. **POST /admin/queue/purge_older_than** — поля: `days` (int 1..365),
   `csrf_token`. Все pending драфты старше N дней получают status="rejected".
   Возвращает `{"status": "ok", "news": N, "author_notes": M}`.

Все POST'ы требуют двойной CSRF (cookie+form). Все требуют BasicAuth с
ADMIN_PASSWORD. CSRF получается из `GET /admin` или `GET /admin/queue`
через regex `name="csrf_token"\s+value="([^"]+)"`.

## Хранилища

- News pending = `news.drafts.DraftStore(news_drafts.json).list_pending()`.
  Структура одной записи (см. `news/drafts.py::NewsDraft`):
  - `draft_id`, `created_at` (ISO8601 с +00:00), `status` ("pending_review"
    / "revised" / ...), `source_news` (dict с title/source/sector/impact_score),
    `post_html`, `claude_json`, `revision_count`, `image_path`, и т.д.
- Author-notes pending = `author_notes.AuthorNoteStore(author_notes_drafts.json).list_pending()`.
  Структура (см. `author_notes.py::AuthorNoteDraft`):
  - `draft_id`, `created_at`, `status`, `rubric`, `claude_json`, `post_html`,
    `revision_count`, `owner_feedback`.

И news, и author_notes pending status'ы: `pending_review` или `revised`.
После reject: `rejected`.

## Где живут файлы

`admin_panel.py` использует константы:
```python
ROOT = Path(__file__).resolve().parent
NEWS_DRAFTS_FILE = ROOT / "news_drafts.json"
AUTHOR_NOTES_FILE = ROOT / "author_notes_drafts.json"
```

В тестах их нужно перенаправить на временные файлы внутри `tmp_path`.
Простейший путь: после `_reload_admin`, прямо подменить
`mod.NEWS_DRAFTS_FILE` и `mod.AUTHOR_NOTES_FILE` через `monkeypatch.setattr`.
Файлы заполняются `json.dump([{...}, ...], file)` со списком dict-записей
в формате `NewsDraft.to_dict()` / `AuthorNoteDraft.to_dict()`.

ВАЖНО: news.drafts.DraftStore и author_notes.AuthorNoteStore инстанцируются
**внутри** хелперов `_list_pending_*`, `_reject_*`, `_purge_older_than` —
они читают `mod.NEWS_DRAFTS_FILE` / `mod.AUTHOR_NOTES_FILE` каждый раз заново.
Поэтому monkeypatch'а на сами константы достаточно.

## Требуемые тесты

1. **test_queue_requires_auth** — GET /admin/queue без auth → 401.

2. **test_queue_renders_pending_news_and_notes** — записать в tmp файлы:
   - 2 news pending (разный impact_score, должны вернуться отсортированными
     по impact desc),
   - 1 news со status="published" (не должен попасть на страницу),
   - 1 author_note pending,
   - GET /admin/queue → 200, в HTML присутствуют draft_id'ы pending, нет
     draft_id опубликованного, виден правильный счётчик "News pending (2)".

3. **test_queue_reject_news_changes_status** — записать 1 news pending,
   GET для cookie+csrf, POST /admin/queue/reject с kind=news → 200
   ok, проверить что в файле теперь status="rejected".

4. **test_queue_reject_author_note_changes_status** — то же для kind=author_note.

5. **test_queue_reject_unknown_kind** — POST с kind="dogfood" → status="error".

6. **test_queue_reject_missing_draft** — POST с draft_id="ghost" →
   status="error", "not found or not pending".

7. **test_queue_reject_already_published** — записать news со status="published",
   POST reject → status="error" (не должен трогать terminal-статусы).

8. **test_queue_reject_csrf_missing** — POST без csrf_token → 403.

9. **test_queue_purge_older_than_threshold** — записать:
   - 1 news pending с created_at = today (UTC),
   - 1 news pending с created_at = today - 10 дней,
   - 1 author_note pending today - 10 дней.
   POST /admin/queue/purge_older_than с days=3 → status="ok", news=1,
   author_notes=1. Сегодняшний news должен остаться pending_review.

10. **test_queue_purge_invalid_days** — POST с days=0 или days=500 →
    status="error", "days must be 1..365".

## Технические требования

- pytest + pytest fixtures (tmp_path, monkeypatch).
- НЕ использовать `unittest.TestCase`.
- TestClient из `fastapi.testclient`.
- Импорты только из stdlib, pytest, fastapi.testclient, и `_reload_admin`
  через тот же шаблон что в `test_admin_security.py`.
- Не выдумывать поля у `NewsDraft`/`AuthorNoteDraft` — используй только те,
  что перечислены выше. Минимально достаточный draft-dict:
  ```python
  news_draft_dict = {
      "draft_id": "abc1",
      "created_at": "2026-05-27T10:00:00+00:00",
      "status": "pending_review",
      "source_news": {"title": "BTC", "source": "Bloomberg", "sector": "ai_crypto",
                      "impact_score": 85, "url": "", "published_at": "", "summary": "",
                      "assets": [], "category": "other", "id": "x"},
      "post_html": "<b>hi</b>",
      "claude_json": {"specific_title": "BTC pumps"},
      "revision_count": 0,
      "owner_feedback": [],
      "updated_at": "",
      "image_path": "",
      "guard_reasons": [],
      "schema_version": "v2",
      "image_origin": "none",
      "image_source_url": "",
      "image_credit": "",
      "image_prompt": "",
      "image_model": "",
      "image_created_at": "",
  }

  note_draft_dict = {
      "draft_id": "n1",
      "created_at": "2026-05-27T10:00:00+00:00",
      "status": "pending_review",
      "rubric": "what_i_understood",
      "claude_json": {"body": "today I learned about FOMO"},
      "post_html": "<b>note</b>",
      "revision_count": 0,
      "owner_feedback": [],
      "updated_at": "",
  }
  ```
- CSRF добывать regex'ом, как в `test_admin_security.py::test_force_post_sanitizes_dangerous_html`.
- ADMIN_PASSWORD="s3cret!Strong#42" во всех тестах.
- Каждый тест — независимый, файлы tmp_path. Файлы записываем через
  `json.dump(list_of_dicts, fp, ensure_ascii=False)`.

## Что вернуть

Один Python-блок ```python ... ``` — полный файл `tests/test_admin_queue.py`.
Без пояснений до или после.
