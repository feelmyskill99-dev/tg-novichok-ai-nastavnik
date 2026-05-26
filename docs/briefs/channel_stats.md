# Задача: scripts/channel_stats.py — базовая аналитика канала

## Контекст

Канал @ai_deposit_diary (deposit_ai) — Telegram-бот публикует посты.
Сейчас никаких бизнес-метрик не собирается. Нужен скрипт-сборщик базовых метрик.

Один прогон = одна запись в `state.json.channel_stats_log[]`.

## Что собрать

Все Telegram-метрики через aiogram Bot API:

1. `subscribers_count` — `bot.get_chat_member_count(CHANNEL_ID)`.
2. `channel_title` — `(await bot.get_chat(CHANNEL_ID)).title`.
3. `bot_can_post` — `(await bot.get_chat_member(CHANNEL_ID, bot.id)).can_post_messages`
   (булево или None если AttributeError для не-admin типов).

Локальные счётчики из JSON-файлов (через `core.json_store.read_json_or_default`):

4. `posts_last_7d`, `posts_last_30d` — посчитать записи в `history.json` (список dict),
   где `datetime` поле — ISO 8601 UTC (например `"2026-05-14T16:00:34+00:00"`).
   Брать от `datetime.now(timezone.utc) - timedelta(days=N)`.
5. `pending_drafts` — словарь из 3 чисел:
   - `news`: `len(news_drafts.json)` (список dict)
   - `author_notes`: `len(author_notes_drafts.json)` (список dict)
   - `weekly_diary`: `len(weekly_diary_drafts.json) if exists else 0`
   Все эти файлы — списки dict. Если файла нет — 0.
6. `active_confirm_trades` — `len(confirm_trades.json)` (dict с trade_id ключами,
   считать `len(...)`). Если файла нет — 0.

Engagement (views/reactions) НЕ собираем — это MTProto, вне scope.

## CLI

```
python scripts/channel_stats.py             # собрать → дописать в state.json → print summary
python scripts/channel_stats.py --json      # то же + распечатать собранный dict как JSON
python scripts/channel_stats.py --no-write  # не писать в state.json, только print
```

## Что использовать

**Уже существующий helper** (тебе не нужно его писать):

```python
# core.content_mix_writer
def append_channel_stats(state_path: Path, stats: dict, *, max_entries: int = 100) -> None:
    ...
```

Просто импортируй и вызови:
```python
from core.content_mix_writer import append_channel_stats
append_channel_stats(state_path, stats)
```

Этот helper сам добавляет `recorded_at` (если в stats его нет), сам обрезает до 100 записей,
сам пишет атомарно. Тебе НЕ нужно ничего из этого делать.

## Контракт собранного dict

```python
stats = {
    "subscribers_count": 47,           # int или None
    "channel_title": "Депозит ...",    # str или None
    "bot_can_post": True,              # bool или None
    "posts_last_7d": 0,                # int
    "posts_last_30d": 14,              # int
    "pending_drafts": {"news": 18, "author_notes": 13, "weekly_diary": 0},
    "active_confirm_trades": 0,        # int
}
```

`recorded_at` НЕ добавляй — append_channel_stats делает это сам.

## Жёсткие правила

1. **Никаких новых зависимостей.** Только установленные: `aiogram`, `aiohttp`, `dotenv`, stdlib.
2. **DNS на Windows**: используй `_ThreadedResolverSession` (см. `scripts/setup_channel.py`).
3. **Atomic JSON**: только через `core.json_store.read_json_or_default` (для чтения
   `history.json` / drafts). Запись — через `append_channel_stats`.
4. **`.env`**: загружай через `load_dotenv(dotenv_path=ROOT / ".env")` где
   `ROOT = Path(__file__).resolve().parents[1]`.
5. **`sys.stdout.reconfigure(encoding="utf-8")`** в начале `main()` — Windows CP1251 ломает print.
6. **Каждый Telegram API вызов в отдельном try/except** — если упал, поле = None,
   summary пишет «n/a». Не валим весь сбор из-за одного API-error.
7. **Никаких docstring длиннее одной строки.**
8. **Не парси JSON руками** — `core.json_store.read_json_or_default(path, default=[])`.
9. **Exit code**: 0 если что-то собрано (даже частично), 1 если фатальная ошибка
   (TELEGRAM_TOKEN / CHANNEL_ID пустые).

## Summary в stdout

Что-то типа:
```
=== CHANNEL STATS ===
  channel:           Депозит под надзором ИИ (@ai_deposit_diary)
  subscribers:       47
  bot can post:      True
  posts last 7d:     0
  posts last 30d:    14
  pending drafts:    news=18 / author_notes=13 / weekly_diary=0
  active trades:     0
  written to:        state.json.channel_stats_log
```

С флагом `--json` — после summary напечатать `json.dumps(stats, ensure_ascii=False, indent=2)`.

С флагом `--no-write` — не вызывать `append_channel_stats`, в summary написать `written to: (skipped --no-write)`.

## Контекстные файлы

Приложены:
- `scripts/setup_channel.py` — образец structure (argparse + aiogram + _ThreadedResolverSession + dotenv)
- `core/json_store.py` — `read_json_or_default`
- `core/content_mix_writer.py` — там УЖЕ ЕСТЬ append_channel_stats, не пиши её, только используй

## Финальный ответ

Один Python-блок ```python ... ``` с полным содержимым `scripts/channel_stats.py`.
Никакого пояснительного текста.
