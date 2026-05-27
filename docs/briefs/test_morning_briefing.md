# Задача: tests/test_morning_briefing.py + tests/test_fear_greed.py

Написать pytest-тесты для двух модулей Stage 14e:
1. `core/fear_greed.py` — F&G индекс с кэшем в state.json
2. `core/morning_briefing.py` — HTML утреннего брифинга

## Стиль

- pytest + tmp_path/monkeypatch для I/O.
- Без unittest.
- HTTP мокаем через `monkeypatch.setattr(httpx, "get", ...)`.
- Каждый тест — один смысл, один-два asserts.

## Тесты для core/fear_greed.py (8 шт)

Изучи модуль перед написанием. Публичные функции:
- `fetch_fear_greed_raw(*, timeout_s=8.0) -> Optional[int]` — прямой API
- `fetch_fear_greed(state_path=None) -> tuple[Optional[int], str]` — с кэшем
- `_label_from_value(value: int) -> str` — internal helper

1. **test_label_strong_fear** — value=10 → "сильный страх"
2. **test_label_fear** — value=30 → "страх"
3. **test_label_neutral** — value=50 → "нейтрально"
4. **test_label_greed** — value=60 → "жадность"
5. **test_label_strong_greed** — value=85 → "сильная жадность"
6. **test_fetch_raw_success** — мок httpx.get вернёт `{'data':[{'value':'42'}]}`,
   функция должна вернуть 42 (int). Используй `monkeypatch.setattr(httpx, "get",
   lambda *a, **kw: _FakeResp(200, {'data':[{'value':'42'}]}))`.
7. **test_fetch_raw_http_error** — мок возвращает status_code=500, функция None.
8. **test_fetch_with_cache_hit** — записать в tmp_path/state.json свежий
   `fear_greed_cache` с value=50, cached_at=NOW. Вызвать `fetch_fear_greed(state_path)`.
   Ассерт: возвращает (50, "нейтрально"). httpx НЕ дёргается (для проверки —
   monkeypatch httpx.get так, чтобы он бросал AssertionError).

`_FakeResp` пример:
```python
class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
    def json(self):
        return self._payload
```

## Тесты для core/morning_briefing.py (10 шт)

Публичные функции:
- `build_morning_briefing_html(market_snapshot, top_news, *, fg_index, fg_label,
  partner_url, bot_username, channel_id_for_links, caption_limit=1024) -> str`
- `fetch_top_news_for_briefing(news_drafts_path, *, now, lookback_hours, limit) -> list[dict]`

1. **test_build_basic** — market={'price':75000,'change_24h':-1.4}, 3 news.
   В тексте есть «🌅 Доброе утро!», «BTC у $75 000», «(-1.40%)», «в минусе».
2. **test_build_direction_plus** — change_24h=+2.5 → "в плюсе"
3. **test_build_direction_minus** — change_24h=-1.5 → "в минусе"
4. **test_build_direction_sideways** — change_24h=0.3 → "в боковике"
5. **test_build_fg_optional** — fg_index=None → строка «Индекс F&G» НЕ
   присутствует. fg_index=25 + label="страх" → «Индекс F&amp;G: 25 — страх.»
   (с амперсандом HTML-escape!).
6. **test_news_message_id_renders_as_internal_link** — news с
   message_id=110 и channel_id_for_links="@chan" → в HTML
   `<a href="https://t.me/chan/110">`.
7. **test_news_external_url_when_no_message_id** — news с url='https://example/x',
   без message_id → в HTML `<a href="https://example/x">`.
8. **test_news_no_url_no_msgid_plain** — news с только title → нет `<a href`,
   но title есть.
9. **test_caption_limit_drops_to_3_news** — 5 длинных новостей, caption_limit=300.
   В выходе должно быть ≤ 3 news bullets (по `text.count("➤")`).
10. **test_html_escapes_titles** — news с title="Hack <script>". В HTML
    есть `&lt;script&gt;`, нет `<script>`.

## Тесты для fetch_top_news_for_briefing (5 шт, в том же файле)

11. **test_fetch_only_published** — создать tmp news_drafts.json с
    смесью status'ов (published / pending_review / rejected). В выходе только
    published.
12. **test_fetch_within_lookback_window** — записи: 5 часов назад (in), 20 часов назад (out).
    Lookback_hours=14 → 1 запись возвращена.
13. **test_fetch_sorts_by_impact_desc** — 3 записи с impact 50/90/70. Выход
    sorted: 90 первой.
14. **test_fetch_limit** — 10 записей, limit=3 → 3 записи.
15. **test_fetch_missing_file** — несуществующий path → возвращает `[]` (не падает).

## Структура news_drafts.json для тестов

```python
{
    "draft_id": "x1",
    "created_at": "2026-05-27T08:00:00+00:00",
    "status": "published",
    "source_news": {
        "title": "BTC pumps", "url": "https://src/btc", "impact_score": 90,
        "source": "test", "published_at": "", "summary": "", "assets": [],
        "category": "other", "sector": "ai_crypto", "id": "x1",
    },
    "claude_json": {"specific_title": "BTC pumps to ATH"},
    "post_html": "...", "revision_count": 0, "owner_feedback": [], "updated_at": "",
}
```

## Импорты

```python
import json
import httpx
from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest

from core.fear_greed import fetch_fear_greed, fetch_fear_greed_raw, _label_from_value
from core.morning_briefing import (
    build_morning_briefing_html,
    fetch_top_news_for_briefing,
)
```

Используй `NOW = datetime(2026,5,27,10,0,tzinfo=timezone.utc)` для тестов с временем.

## Что вернуть

ОДИН Python-блок ```python ... ``` — оба теста (fear_greed + morning_briefing)
объединить в **ОДИН файл** `tests/test_morning_briefing.py`. Это упрощает
запуск и не плодит мелкие файлы. Сохранить структуру через комментарии:

```python
# =============== core/fear_greed.py ===============
...
# =============== core/morning_briefing.py ===============
...
```
