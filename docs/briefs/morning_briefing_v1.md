# Spec: Morning Briefing v1 («Доброе утро + 5 новостей»)

Stage 14e. Заменяет текущий `scheduled_morning` (market_chart с
graphsript-only) форматом, увиденным у @invest_zonaa и @crypto_hd:

    🌅 Доброе утро!
    
    Сегодня рынок [в плюсе/в минусе/в боковике], BTC у $XX,XXX (±X.X%).
    Индекс F&G: XX — [страх/жадность/нейтрал].
    
    📊 Главное за ночь:
    
    ➤ <a href="...">Заголовок новости 1</a>
    ➤ <a href="...">Заголовок новости 2</a>
    ➤ <a href="...">Заголовок новости 3</a>
    ➤ Заголовок новости 4 (без ссылки если нет)
    ➤ Заголовок новости 5
    
    🐹 Какой пост недели хочется обсудить — пиши в @ai_deposit_diary_bot.
    
    📈 [Я торгую здесь → Gate.io](utm_link)

## Цели

1. Заменить «голый chart» утренним брифингом — формат как у конкурентов.
2. Создать **сводный пост** с overview рынка + ссылки на главные новости
   ночи. Удерживает читателя.
3. Сохранить chart как **картинку к посту** (caption=1024 chars).
4. Это **morning_briefing** sector — отдельный тип в content_mix_log
   (не market, не news).

## Источники данных

- **Market snapshot**: `Market.ticker()` + `Market.ohlcv()` как сейчас.
- **F&G index**: новый источник (alternative.me API или fallback из
  существующего scoring). Если недоступен — пропускаем строку.
- **Топ-5 новостей за ночь**: из `news_drafts.json` со status="published"
  AND `created_at` за последние ~14 часов (с 19:00 вчера до 10:00 сегодня
  МСК). Сортировка по `source_news.impact_score` desc, top-5.
- **Картинка**: chart как сейчас (`make_chart_tv` или `make_chart`).

## Что НЕ менять

- `force_education=True` (вечерний слот) — остаётся как есть, никакого
  утреннего брифинга.
- `mode == "fallback_education"` (нет market data) — остаётся education.
- `mode == "flash"` (резкий ход >FLASH_THRESHOLD) — остаётся flash.

Утренний брифинг ТОЛЬКО для `source == "scheduled_morning"` и нормального
рыночного режима.

## Структура HTML (caption ≤1024)

Целевой формат:

```html
🌅 <b>Доброе утро!</b>

Сегодня рынок {direction}, {SYMBOL} у ${price:,.0f} ({change:+.2f}%).
Индекс F&amp;G: {fg_value} — {fg_label}.

📊 <b>Главное за ночь:</b>

➤ <a href="{msg_link or url}">{title_1}</a>
➤ <a href="{msg_link or url}">{title_2}</a>
➤ ...

🐹 <i>Какой пост недели хочется обсудить — пиши в @ai_deposit_diary_bot.</i>

📈 <b><a href="{partner_url}">Я торгую здесь → Gate.io</a></b>
```

`direction` — «в плюсе», «в минусе», «в боковике» (по change_24h:
≥+1% → плюсе, ≤-1% → минусе, иначе боковик).

## Контракт реализации

### Шаг 1: новая функция `build_morning_briefing()`

В отдельном модуле `core/morning_briefing.py`:

```python
def build_morning_briefing_html(
    market_snapshot: dict,
    top_news: list[dict],
    *,
    fg_index: int | None = None,
    fg_label: str = "",
    partner_url: str = "",
    bot_username: str = "",
) -> str: ...
```

`market_snapshot` — из существующего `Publisher.publish` без изменений
(symbol, price, change_24h, rsi, ema50/200, ...).

`top_news` — список из 3-5 dict'ов формата:
```python
{
    "title": "...",        # specific_title или source_news.title
    "url": "...",          # source URL (опционально)
    "message_id": 108,     # TG message_id канала, опционально
}
```

Если `message_id` есть → внутренняя `t.me/<chan>/<msg>` ссылка через
`core.daily_digest._build_message_link` (выделить общий helper).
Иначе используем `url` (внешний источник). Если нет ни того ни
другого — plain text.

Возвращает HTML ≤1024 chars. Если длина не влезает — приоритет: header,
market line, top-3 news (вместо 5).

### Шаг 2: модифицировать `Publisher.publish`

Когда `source == "scheduled_morning"` и режим `normal`:

```python
if source == "scheduled_morning" and mode == "normal":
    from core.morning_briefing import build_morning_briefing_html
    from core.fear_greed import fetch_fear_greed  # новый модуль
    top_news = _fetch_top_news_for_briefing(...)  # из news_drafts.json
    fg = fetch_fear_greed()  # (value, label) or (None, "")
    text = build_morning_briefing_html(
        market_snapshot, top_news,
        fg_index=fg[0], fg_label=fg[1],
        partner_url=PARTNER_URL or "",
        bot_username=BOT_USERNAME,
    )
    # Дальше: post_type = "morning_briefing"
    # send_post_with_optional_image(text, chart_path, ...)
```

### Шаг 3: новый helper `_fetch_top_news_for_briefing`

Читает `news_drafts.json`, фильтрует:
- `status == "published"`
- `created_at` в окне `(now - 14h, now)` UTC
- Сортирует по `source_news.impact_score` desc
- Возвращает top-5 dict'ов с полями title/url/message_id (если есть)

### Шаг 4: новый модуль `core/fear_greed.py`

```python
def fetch_fear_greed() -> tuple[int | None, str]:
    """Возвращает (value 0-100, label) или (None, '').
    
    API: https://api.alternative.me/fng/?limit=1
    Кэшируется на 1 час в state.json чтобы не дёргать API каждый раз.
    """
```

### Шаг 5: тесты

- `tests/test_morning_briefing.py` — для build_morning_briefing_html:
  caption-fit, fallback на 3 новости, direction calculation,
  F&G optional, escape titles.
- `tests/test_fear_greed.py` — mock httpx, fallback на None при ошибке.

## Что выносим в follow-up (не делать сейчас)

- Запись `message_id` в content_mix_log для news постов. Это другая
  работа (надо пробросить msg.message_id из news_publisher.send в
  _log_post_event). Без неё дайджест и брифинг будут показывать
  внешние URL вместо t.me-ссылок — приемлемо для v1.
- Изменение base_channel_style.md под утренний формат.

## Риски

- Caption 1024 ограничение. Если 5 новостей + market + partner не
  влезают — отрезать до 3 новостей. Тестом покрыть.
- Если все 5 новостей за ночь имеют only внешние URL (нет message_id)
  — пост превращается в RSS-ленту. Это **видно глазами**, надо контроль
  через mix: max 3 внешних, остальное — на наши t.me/<chan>/<msg>.
- F&G API падает → fallback скрывает строку, остальное публикуется.
- Слишком частые рестарты бота → misfire_grace_time=4h уже есть из
  Stage 14b, должен сработать.

## Acceptance

- В 10:00 МСК (или ENV POST_MORNING_HOUR) выходит ОДИН пост с
  caption ≤1024 chars + chart-картинка.
- В нём строка с ценой BTC + F&G (если работает) + 3-5 буллетов с
  главными новостями ночи.
- В `content_mix_log` запись с `post_type="morning_briefing"`,
  `category="market"` (или новая категория `briefing`).
- Все 128+ существующих тестов проходят.
- Новые тесты `test_morning_briefing.py` и `test_fear_greed.py`
  проходят.
