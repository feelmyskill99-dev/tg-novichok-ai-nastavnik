# Задача: написать tests/test_news_pipeline.py

## Цель

Pytest-тесты для трёх единиц news-pipeline (без Claude/сети):
- `news.models.NewsItem` — конструкция, нормализация, hashing.
- `news.cache.NewsCache` — JSON save/load round-trip.
- `news.deduplicator.NewsDeduplicator` — dedup по id, url, similarity.
- `news.scorer.NewsScorer` — рулесет impact_score, category/sector detection.

## Правила

1. pytest + tmp_path. Без моков.
2. Без эмодзи. Короткие имена.
3. Без сети, без Claude.
4. Импорты:
   ```python
   from news.models import NewsItem, make_news_id, CATEGORIES, SECTORS
   from news.cache import NewsCache
   from news.deduplicator import NewsDeduplicator, _tokenize_title, TITLE_SIMILARITY_THRESHOLD
   from news.scorer import NewsScorer
   from news.config import NewsConfig
   ```
5. Файл начинается со стандартного блока:
   ```python
   from __future__ import annotations
   import sys, json
   from datetime import datetime, timezone, timedelta
   from pathlib import Path
   import pytest
   ROOT = Path(__file__).resolve().parent.parent
   sys.path.insert(0, str(ROOT))
   ```

## ВАЖНО про assertions

В `verdict.reasons: list[str]` нельзя писать `"X" in reasons` — это точное
сравнение элементов списка. Используй `any("X" in r for r in reasons)`.
Этот тест-файл такого паттерна не требует (нет reasons), но имей в виду.

## Покрытие — обязательные сценарии

### NewsItem (~6 тестов)

1. `test_news_item_post_init_generates_id` — без явного id, после конструктора `item.id` непуст и == 16 hex chars.
2. `test_news_item_assets_uppercased_and_stripped` — assets `["btc ", " eth"]` → `["BTC", "ETH"]`.
3. `test_news_item_collected_at_auto_set` — без явного collected_at, поле проставлено в ISO.
4. `test_make_news_id_stable_for_same_title_source` — один и тот же `make_news_id(title, source)` даёт одинаковый id.
5. `test_make_news_id_differs_with_normalization` — заголовки с разным регистром/whitespace но одинаковой сутью дают тот же id (нормализация).
6. `test_news_item_to_dict_round_trip` — `NewsItem.from_dict(item.to_dict())` равен исходному по полям id/title/url.

### NewsCache (~3 теста)

7. `test_news_cache_save_load_round_trip` — `cache.save([item1, item2])` → `cache.load()` возвращает 2 NewsItem с теми же id.
8. `test_news_cache_load_missing_returns_empty` — путь не существует → `[]`.
9. `test_news_cache_load_corrupt_returns_empty` — записан невалидный JSON → `[]`, не падает.

### NewsDeduplicator (~6 тестов)

Все тесты создают `NewsDeduplicator(tmp_path / "h.json")` и пишут в него через `remember()` или вручную через json.

10. `test_dedup_empty_history_not_duplicate` — на пустой истории `is_duplicate(item)` → False.
11. `test_dedup_remember_then_duplicate` — `dedup.remember(item, "published_channel")`, потом `dedup.is_duplicate(item)` → True.
12. `test_dedup_url_match_is_duplicate` — два item с одинаковым `url` но разными title → True.
13. `test_dedup_similar_title_cross_source_is_duplicate` — два item с **очень похожими** titles (отличаются только источником/одним словом) → True. Подсказка: используй titles типа `"BlackRock Bitcoin ETF sees record inflows of $500M today"` и `"BlackRock Bitcoin ETF records record inflows totaling $500M today"`. Пороги: `TITLE_SIMILARITY_THRESHOLD=0.65` после токенизации.
14. `test_dedup_unrelated_titles_not_duplicate` — два title с разной тематикой → False. Например `"Bitcoin ETF approval"` и `"Solana memecoin pump"`.
15. `test_dedup_old_record_outside_window_not_duplicate` — запись с `posted_at` старше `window_hours` — не считается. Делай вручную: запиши JSON с старой датой.

### NewsScorer (~5 тестов)

Создавай `NewsConfig()` (frozen dataclass с дефолтами) и `NewsScorer(config)`.

16. `test_scorer_detects_etf_sector_and_high_base` — item с title `"BlackRock spot ETF approval by SEC sees record inflows"` (источник `"CoinDesk"`, assets `["BTC"]`) → после score(): `sector == "regulation_etf_institutional"`, `impact_score >= 85`.
17. `test_scorer_memecoin_zero_when_disabled` — item title `"DOGE pumps 200% on memecoin frenzy"`, sector детектится как `"memecoins_low_priority"`, `cfg.news_allow_memecoins=False` (дефолт) → `impact_score == 0`.
18. `test_scorer_price_prediction_penalty` — item с title `"Bitcoin price prediction: BTC could hit $200K by 2026"` → impact_score меньше base BTC-новости (penalty -20). Сравни два item: один с прогнозом, второй без — у первого score ниже.
19. `test_scorer_sketchy_source_penalty` — source `"some-blog.medium.com"` → impact_score значительно ниже (-50). Сравни с тем же item но `source="CoinDesk"`.
20. `test_scorer_score_clamped_0_100` — даже при множественных бонусах impact_score ≤ 100; при множественных penalties >= 0.

## Базовый NewsItem helper

В начале файла:

```python
def _mk_item(
    *,
    title: str = "BlackRock spot ETF approval by SEC sees record inflows",
    url: str = "https://example.com/news/1",
    source: str = "CoinDesk",
    summary: str = "",
    assets: list[str] | None = None,
    published_at: str | None = None,
) -> NewsItem:
    published_at = published_at or datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
    return NewsItem(
        title=title,
        url=url,
        source=source,
        published_at=published_at,
        summary=summary,
        assets=assets or [],
    )
```

## Что НЕ делать

- Не вызывать `os.getenv` или `load_dotenv` — `NewsConfig()` создаётся с дефолтами.
- Не моки.
- Не пиши `if __name__ == "__main__"` в конце.
- Не дёргай collector.py / orchestrator.py / analyzer.py / publisher.py — там сеть и Claude.

## Финальный ответ

Один Python-блок ```python ... ``` готового файла. Без пояснений.
