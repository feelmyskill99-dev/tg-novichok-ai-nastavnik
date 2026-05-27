# Задача: tests/test_daily_digest.py

Написать pytest-тесты для `core/daily_digest.py` — Stage 14d, ежедневный
«ТОП ДНЯ» дайджест.

Стиль: pytest + tmp_path/monkeypatch если нужно, **без unittest**, без
TestClient (это чистая функция). Тесты независимые, по одному ассерту
на смысл.

## Что тестируем

Функция `build_digest_html(log_list, *, channel_id_for_links="", now=None,
min_posts=3, max_posts=12) -> Optional[str]`.

**Что она делает:**
1. Фильтрует записи из log_list где `published_to == "channel"` и
   `timestamp.date() == now.date()` (UTC сравнение).
2. Если таких записей < min_posts → возвращает None.
3. Сортирует по timestamp ASC.
4. Берёт первые max_posts.
5. Дедупит по нормализованному title (lower, первые 80 символов).
6. Формирует HTML: header «🎯 ТОП ДНЯ — <русская дата по МСК>» + двойные
   переносы между пунктами.
7. Первый пункт — `❕`, остальные — `▫️`.
8. Если у записи есть `message_id` И channel_id_for_links непустой —
   рендерим как `<a href="...">{title}</a>`. Иначе plain HTML-escaped text.
9. Ссылка: `@username` → `https://t.me/<username>/<msg>`,
   numeric `-100xxxx` → `https://t.me/c/<xxxx>/<msg>` (-100 префикс
   удалён). Просто `username` (без @) тоже → `https://t.me/<username>/<msg>`.
10. Title escape'ится HTML (`<`, `>`, `&`). Длиннее 100 → обрезаем до 99 + `…`.
11. Дата в header'е — на МСК (UTC+3), формат `понедельник, 27 мая` (русское
    название дня недели + день + русский месяц).

## Контракт log-записи

```python
{
    "timestamp": "2026-05-27T10:00:00+00:00",  # ISO UTC
    "post_type": "market_chart",
    "category": "market",
    "published_to": "channel",  # либо "owner"
    "title": "BTC у EMA, RSI слабый",
    "source": "scheduled_morning",
    "message_id": 108,  # опционально
}
```

## Тесты (10 штук, по 1 ассерту на смысл)

1. **test_returns_none_when_below_min_posts** — 2 поста сегодня, min_posts=3.
   Ожидаем None.

2. **test_returns_html_when_min_posts_reached** — 3 поста сегодня в канал.
   Возвращает строку, начинающуюся с `🎯`.

3. **test_filters_out_yesterday_posts** — 2 сегодня + 5 вчера. С min_posts=3
   ожидаем None (вчерашние не считаются).

4. **test_filters_out_owner_posts** — 2 published_to=channel + 5
   published_to=owner. min_posts=3 → None.

5. **test_sorts_by_timestamp_ascending** — 3 поста с timestamp в обратном
   порядке. Проверить, что первый по тексту в HTML — самый ранний.

6. **test_caps_at_max_posts** — 20 постов сегодня, max_posts=5. В HTML
   должно быть ровно 5 буллетов (1× ❕ + 4× ▫️). Через `text.count("▫️")` и `text.count("❕")`.

7. **test_message_id_renders_as_anchor** — пост с message_id=108,
   channel_id_for_links="@ai_deposit_diary". В HTML присутствует
   `<a href="https://t.me/ai_deposit_diary/108">`.

8. **test_numeric_channel_link** — channel_id_for_links="-1001234567890",
   message_id=42. Ожидаемая ссылка: `https://t.me/c/1234567890/42`
   (без `-100`).

9. **test_no_message_id_renders_as_plain** — пост без message_id. В HTML
   есть title но НЕТ `<a href`.

10. **test_html_escapes_title** — title=`Hack <script>alert(1)</script>`.
    В выходном HTML присутствует `&lt;script&gt;`, **отсутствует** сырое
    `<script>`.

## Импорты

```python
from datetime import datetime, timezone, timedelta
from core.daily_digest import build_digest_html
```

`now` параметр функции — это `datetime` с tzinfo=UTC. Используйте
фиксированный `now = datetime(2026, 5, 27, 18, 0, tzinfo=timezone.utc)` —
это «27 мая 21:00 МСК», воскресенье… проверь сам какой день недели по
календарю 2026 — но это для теста дня недели не важно (тесты 1-10 не
завязаны на конкретное название дня).

Помощник для timestamp:
```python
def _ts(hours_ago: float) -> str:
    return (datetime(2026,5,27,18,0,tzinfo=timezone.utc) -
            timedelta(hours=hours_ago)).isoformat(timespec="seconds")
```

## Что вернуть

Один Python-блок ```python ... ``` — полный файл `tests/test_daily_digest.py`.
Без обрамляющего текста.
