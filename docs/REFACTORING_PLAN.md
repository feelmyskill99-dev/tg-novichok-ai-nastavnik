# Рефакторинг-план: «Тг новичок и AI наставник»

Дата аудита: 2026-05-13

Цель документа: не «переписать всё красиво», а сначала убрать риски потери данных, дублей публикаций/ордеров и нестабильного запуска. Архитектурные переносы идут только после стабилизации поведения.

## Главные принципы

- Сначала безопасность состояния и внешних действий, потом разнос `bot.py` по модулям.
- Любая публикация в канал или approve сделки должна быть идемпотентной.
- JSON-хранилища должны писаться атомарно и с межпроцессной блокировкой.
- Перед крупной миграцией на SQLite нужен общий storage-интерфейс и тесты совместимости.
- Админка по умолчанию должна быть локальной и fail-fast без явного пароля.

---

## Этап 0: Подготовка и страховка (0.5 дня)

### 0.1 Зафиксировать baseline

- Снять `git status --short`.
- Сделать копию рабочих JSON-файлов в `backups/YYYYMMDD_HHMMSS/`.
- Зафиксировать, какие процессы реально могут писать в проект: scheduler, polling, CLI-команды, admin panel, Task Scheduler.

### 0.2 Проверить зависимости и запуск

Проблемы:

- `admin_panel.py` использует `Form`, но в `requirements.txt` нет `python-multipart`.
- `tests/health_check.py` использует `requests`, но зависимости нет.
- `test_minimal.py` запускает `uvicorn.run()` на импорт и может повесить `pytest`.

Действия:

- Добавить `python-multipart`.
- Либо добавить `requests`, либо переписать health-check на уже имеющийся `httpx`.
- Перенести `test_minimal.py` в `scripts/dev_minimal_server.py` или завернуть запуск в `if __name__ == "__main__"`.
- Проверить:
  - `python -m compileall -q bot.py admin_panel.py core news trading author_notes.py weekly_diary.py`
  - `python bot.py --persistence-check`

---

## Этап 1: Критические правки без большой перестройки (1-2 дня)

### 1.1 Единый atomic JSON store с межпроцессным lock

Проблема:

Сейчас многие места делают `load -> mutate -> write_text` без lock и atomic replace. `asyncio.Lock` недостаточен, потому что проект может писать из разных процессов: scheduler, CLI, admin panel, Task Scheduler.

Затрагиваемые файлы:

- `state.json`
- `history.json`
- `news_cache.json`
- `news_history.json`
- `news_drafts.json`
- `author_notes_drafts.json`
- `weekly_diary_drafts.json`
- `paper_trades.json`
- `trade_journal.json`
- `confirm_trades.json`
- `live_trades.json`
- `live_trade_journal.json`
- `mistake_tracker_state.json`

Решение:

- Добавить `core/json_store.py`.
- Использовать межпроцессную блокировку: `portalocker` или `filelock`.
- Записывать через временный файл в той же директории:
  - `path.tmp.<pid>`
  - `flush`
  - `os.replace(tmp, path)`
- При битом JSON:
  - сделать backup `name.corrupt.YYYYMMDDTHHMMSSZ.json`
  - вернуть дефолт
  - не перезаписывать оригинал до следующего валидного `update_json()`
- API должен быть синхронным, чтобы его могли использовать текущие sync-store классы:

```python
def load_json(path: Path, default: Any, expected_type: type) -> Any: ...
def save_json(path: Path, value: Any) -> None: ...
def update_json(path: Path, default: Any, expected_type: type, mutator: Callable[[Any], Any]) -> Any: ...
```

Верификация:

- Unit-test на corrupt backup.
- Multiprocessing-test: 3 процесса по 50 append-операций в один JSON, итоговая длина 150, JSON валиден.
- Regression-test для старых draft-файлов.

### 1.2 Идемпотентность publish/approve до внешнего API

Проблема:

Сейчас некоторые обработчики сначала отправляют пост/ордер, а потом меняют статус на `published` или следующий trading-state. При двойном клике, повторном callback или двух процессах возможны дубли.

Зоны риска:

- `news_publish:*`
- `author_publish:*`
- `weekly_publish:*`
- CLI `--publish-news-draft`
- CLI `--publish-author-note`
- confirm approve в `ConfirmBroker.approve_trade()`

Решение для публикаций:

- Под lock прочитать draft.
- Если статус terminal (`published`, `rejected`) - выйти.
- Если статус `publishing` - ответить владельцу «уже публикуется».
- Поставить `status = "publishing"` и `publish_attempt_id`.
- Выполнить Telegram send.
- Под lock заменить на `published`, сохранить `telegram_message_id` при наличии.
- При ошибке поставить `publish_failed` с текстом ошибки и оставить возможность ручного retry.

Решение для confirm approve:

- Под lock перевести `awaiting_confirmation -> approving`.
- После этого второй approve должен видеть `approving` и не выставлять новый entry.
- После успешного `create_order` сохранять `entry_order_id` сразу.
- При ошибке биржи переводить в `failed` с причиной.

Верификация:

- Тест двойного вызова publish-handler с fake Telegram client: отправка ровно один раз.
- Тест двойного approve с fake exchange: `place_limit_entry` вызван ровно один раз.

### 1.3 Telegram long-message guard

Проблема:

Есть `TELEGRAM_MESSAGE_LIMIT = 4096`, но текстовые сообщения отправляются одним `send_message`. При длинном HTML пост может упасть.

Решение:

- Добавить helper `send_long_html(bot, chat_id, html_text, ...)`.
- Делить по абзацам, сохраняя валидный HTML.
- Если сообщение с картинкой не влезает в caption:
  - фото с короткой подписью
  - полный текст через `send_long_html`
  - кнопки прикреплять к последнему текстовому сообщению

Верификация:

- Тест на 9000 символов: отправляется 3 сообщения, ни одно не больше 4096.
- Тест на HTML-теги: не режем внутри `<a href=...>`.

### 1.4 Починить `--post-now` и глобальные зависимости

Проблема:

`Publisher.publish()` в education/fallback ветке использует глобальный `mistake_tracker`, который инициализируется только в scheduler-mode. CLI `--post-now` может упасть.

Решение:

- Инициализировать `MistakeTracker` внутри `Publisher.__init__` или передавать в `Publisher` явно.
- Убрать зависимость publish-flow от глобальных `styleguard` / `mistake_tracker`.
- `StyleGuard` должен быть optional dependency, но не `None` в runtime.

Верификация:

- `python bot.py --post-now` при недоступном рынке уходит в fallback без `AttributeError`.

### 1.5 Админка: безопасный минимум

Проблема:

Админка по умолчанию имеет `ADMIN_PASSWORD=changeme`, простой compare, bind на `0.0.0.0`, и endpoint публикует произвольный HTML в канал.

Решение:

- Если `ADMIN_PASSWORD` не задан или равен `changeme`, админка не стартует.
- Использовать `secrets.compare_digest`.
- По умолчанию bind `127.0.0.1`; `0.0.0.0` только явным env-флагом.
- Добавить CSRF token для POST `/admin/force_post`.
- Для `draft_text` выбрать один режим:
  - либо plain-text publish с HTML-escape,
  - либо allowlist HTML-тегов (`b`, `i`, `code`, `a`) через sanitizer.
- Не генерировать пароль в лог. Логи не должны становиться хранилищем секретов.

Верификация:

- Без `ADMIN_PASSWORD` приложение падает с понятной ошибкой.
- Неверный пароль не проходит.
- POST без CSRF не проходит.

### 1.6 Внешние API: таймауты без блокировки event loop

Проблема:

Простой `asyncio.wait_for(coro)` не решит sync-вызовы `ccxt`, `Anthropic`, `OpenAI`, потому что они уже блокируют поток.

Решение:

- Для sync-клиентов использовать `asyncio.to_thread(...)` или перейти на async-клиенты там, где они доступны.
- Retry-helper должен принимать callable/factory, а не готовую coroutine:

```python
async def run_with_timeout(factory, *, timeout_s: float, retries: int = 1):
    last_exc = None
    for attempt in range(retries + 1):
        try:
            return await asyncio.wait_for(factory(), timeout=timeout_s)
        except Exception as exc:
            last_exc = exc
            if attempt == retries:
                raise
            await asyncio.sleep(2)
    raise last_exc
```

- Для `ccxt` также задать client timeout в конфиге exchange.
- Для RSS не использовать `feedparser.parse(url)` напрямую без timeout. Сначала скачать через `httpx.AsyncClient(timeout=...)`, затем отдать bytes/text в feedparser.

Верификация:

- Fake API, который спит 100 секунд, прерывается за заданный timeout.
- Scheduler job не зависает навсегда из-за одного источника.

### 1.7 `.env` и секреты

Текущий `.gitignore` уже исключает `.env`, поэтому автоматическая ротация всех ключей нужна только если файл был отправлен в чат, коммит, облако или доступен посторонним.

Действия:

- Добавить `env.example`.
- Добавить `scripts/check_env.py` в обязательный smoke-check.
- Опционально перенести `.env` из корня в `%APPDATA%/ai_mentor/.env`, но не делать это первым шагом, чтобы не сломать Task Scheduler.
- Никогда не логировать токены, URL с токенами и API-secret.

---

## Этап 2: Небольшая архитектурная стабилизация (2-4 дня)

### 2.1 Storage-интерфейсы перед SQLite

Перед миграцией на SQLite нужно скрыть текущие JSON-файлы за интерфейсами:

- `DraftStore`
- `HistoryStore`
- `StateStore`
- `TradeStore`
- `JournalStore`

Сначала реализация остается JSON, но уже через `core/json_store.py`. Это даст тесты и позволит мигрировать на SQLite без переписывания бизнес-логики.

### 2.2 Вынести content mix

Проблема:

`compute_content_mix()` в `bot.py` и `get_content_mix_html()` в `admin_panel.py` дублируют логику.

Решение:

- `core/content_mix.py`
- `admin_panel.py` только рендерит результат
- `bot.py` только получает hint

### 2.3 AppConfig без тотального переписывания

Проблема:

`os.getenv` и `from_env()` разбросаны по модулям.

Решение:

- Создать `core/env_helpers.py` для `_bool`, `_int`, `_float`, `_str`.
- Затем создать `AppConfig`, но не удалять сразу `NewsConfig.from_env()` / `TradingConfig.from_env()`.
- На первом шаге `AppConfig` агрегирует существующие config-классы.
- Полное удаление старых `from_env()` делать позже, когда тесты есть.

### 2.4 Разделить `bot.py` по границам ответственности

Очередность:

1. `handlers/`
   - `confirm.py`
   - `news.py`
   - `author_notes.py`
   - `weekly.py`
   - `_utils.py`

2. `posting/`
   - `builder.py`
   - `telegram_send.py`
   - `publisher.py`

3. `market/`
   - `market_data.py`
   - `chart_tv.py`
   - `chart_mpl.py`

4. `cli.py`
   - argparse-команды
   - старый `python bot.py --post-now` временно оставить как compatibility wrapper

### 2.5 Долгоживущий Bot в scheduler jobs

Проблема:

Некоторые jobs создают новый `Bot`, отправляют сообщение, закрывают session.

Решение:

- В `run_scheduler_forever()` создать общий `AppContext`.
- Передавать `bot`, stores, config и clients в jobs явно.
- Закрывать sessions только на shutdown.

### 2.6 StyleGuard как блокировка, а не автопубликация fallback

Проблема:

`StyleGuard` сейчас почти не участвует в pipeline.

Решение:

- Проверять payload/post перед отправкой.
- При fail:
  - не публиковать в канал
  - слать владельцу причину
  - сохранять draft/rejected state
- Не отправлять fallback в канал автоматически из-за style-fail: это может скрыть проблему и загрязнить канал.

---

## Этап 3: Тесты и эксплуатация (3-5 дней)

### 3.1 Приоритетные тесты

Первые тесты:

1. `tests/test_json_store.py`
   - atomic write
   - corrupt backup
   - multiprocessing append

2. `tests/test_publish_idempotency.py`
   - двойной news publish не дублирует Telegram send
   - двойной author publish не дублирует Telegram send
   - `publish_failed` можно повторить вручную

3. `tests/test_confirm_idempotency.py`
   - двойной approve не дублирует exchange order
   - stale callback не проходит

4. `tests/test_telegram_send.py`
   - split >4096
   - split caption >1024
   - reply_markup на правильном сообщении

5. `tests/test_startup.py`
   - `admin_panel` импортируется при наличии зависимостей
   - `--post-now` не падает при fallback

6. `tests/test_content_mix.py`
   - пустой лог
   - мало данных
   - перекос категорий
   - channel-only vs all

7. `tests/test_trading_safety.py`
   - kill switch
   - whitelist
   - RR
   - дневной убыток
   - leverage cap

8. `tests/test_news_pipeline.py`
   - duplicate skip
   - below threshold skip
   - guard-blocked draft

9. `tests/test_json_compat.py`
   - старые drafts без новых полей не ломают загрузку

10. `tests/test_admin_security.py`
    - default password rejected
    - CSRF required
    - unsafe HTML sanitized/escaped

### 3.2 Health-check

Добавить read-only endpoint или CLI-команду:

```json
{
  "ok": true,
  "last_post_iso": "2026-05-13T10:00:00+03:00",
  "pending_news_drafts": 2,
  "pending_author_notes": 1,
  "active_trades": 0,
  "scheduler_hint": "alive"
}
```

Минимальный вариант для Windows Task Scheduler:

- `python bot.py --persistence-check`
- отдельный watchdog script, который проверяет время последней записи в `outputs/scheduler.log` и `history.json`

### 3.3 Metrics and logs

- Оставить текущий rotating file log.
- Добавить redact-фильтр для полей:
  - `token`
  - `api_key`
  - `secret`
  - `authorization`
- Счётчики хотя бы в логах:
  - `post_published`
  - `post_failed`
  - `claude_failed`
  - `telegram_failed`
  - `json_corrupt_recovered`
  - `confirm_approved`
  - `confirm_failed`

### 3.4 SQLite migration

SQLite делать только после этапов 1-2.

Порядок:

1. Storage-интерфейсы уже есть.
2. Написать SQLite implementation behind same interfaces.
3. Написать `scripts/migrate_json_to_sqlite.py`.
4. Миграция должна быть dry-run first:
   - прочитать JSON
   - показать количество записей по типам
   - проверить обязательные поля
   - ничего не писать без `--apply`
5. После миграции оставить read-only fallback на JSON на один релиз.

Минимальные таблицы:

```sql
CREATE TABLE state_kv (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE post_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    datetime TEXT NOT NULL,
    post_type TEXT NOT NULL,
    published_to TEXT,
    source TEXT,
    short_summary TEXT,
    payload_json TEXT NOT NULL
);

CREATE TABLE drafts (
    draft_id TEXT PRIMARY KEY,
    draft_type TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    payload_json TEXT NOT NULL
);

CREATE TABLE trades (
    trade_id TEXT PRIMARY KEY,
    trade_type TEXT NOT NULL,
    status TEXT NOT NULL,
    symbol TEXT,
    created_at TEXT,
    updated_at TEXT,
    payload_json TEXT NOT NULL
);

CREATE TABLE journals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    journal_type TEXT NOT NULL,
    event_type TEXT NOT NULL,
    logged_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
```

---

## Что не делать

- Не полагаться на `asyncio.Lock` как на защиту JSON, если есть шанс нескольких процессов.
- Не писать сгенерированный пароль админки в лог.
- Не делать regex-only security для HTML как единственную защиту, если разрешается HTML.
- Не начинать с массового разрезания `bot.py`, пока publish/approve не идемпотентны.
- Не мигрировать сразу в SQLite без storage-интерфейсов и тестов совместимости.
- Не отправлять fallback в канал при любой ошибке style validation.

---

## Критерии готовности

### Этап 1 готов, когда:

- Все JSON-записи идут через atomic store с межпроцессным lock.
- Corrupt JSON получает backup.
- Двойной publish не даёт дубль в канал.
- Двойной confirm approve не даёт второй order.
- Длинные Telegram сообщения режутся безопасно.
- `python bot.py --post-now` не падает в fallback-ветке.
- Админка не стартует с дефолтным паролем.
- `python -m compileall` проходит.

### Этап 2 готов, когда:

- Content mix живёт в одном модуле.
- Основные хендлеры вынесены из `bot.py`.
- Config читается централизованно или через общий helper.
- Scheduler jobs используют общий context, а не пересоздают клиентов без необходимости.
- Старые CLI-команды остаются совместимыми.

### Этап 3 готов, когда:

- Есть тесты на storage, idempotency, Telegram split, safety и news pipeline.
- Health-check показывает состояние без внешних API.
- Логи не содержат секреты.
- SQLite migration проходит dry-run и apply на копии данных.

---

## Рекомендуемый первый PR

Первый PR должен быть маленьким:

1. Добавить недостающие зависимости.
2. Убрать автозапуск `uvicorn` из `test_minimal.py`.
3. Добавить `core/json_store.py`.
4. Перевести `state.json`, `history.json`, `news_drafts.json` на новый store.
5. Добавить тесты на atomic write и corrupt backup.

После этого можно брать publish idempotency отдельным PR.
