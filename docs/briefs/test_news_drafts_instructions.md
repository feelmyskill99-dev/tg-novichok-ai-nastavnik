# Задача: tests/test_news_drafts_instructions.py

## Цель

Тесты для констант и pure-helpers в `news.drafts`, связанных с
regenerate/revise flow (БЕЗ Claude API). Покрываем:
- `REGENERATE_INSTRUCTION` / `REVISE_INSTRUCTION` — текст констант
- `MAX_DRAFTS` — константа (DraftStore-cap)
- `_source_news_for_claude(draft)` — повторное покрытие (отдельные edge cases)
- Структура user_payload, которая собирается в `regenerate_payload` /
  `revise_payload` ДО вызова Claude — но без вызова Claude!

ВАЖНО: НЕ вызывай `regenerate_payload()` и `revise_payload()` целиком —
они дёргают Claude. Тестируй только что constants/helpers корректны.

## Правила

1. pytest. Без моков Anthropic.
2. Без эмодзи.
3. Импорты:
   ```python
   import sys
   from pathlib import Path
   import pytest
   ROOT = Path(__file__).resolve().parent.parent
   sys.path.insert(0, str(ROOT))
   from news.drafts import (
       NewsDraft, MAX_DRAFTS,
       REGENERATE_INSTRUCTION, REVISE_INSTRUCTION,
       _source_news_for_claude,
   )
   ```

## Helper NewsDraft

```python
def _mk_draft(
    *, source_news_overrides: dict | None = None,
    claude_json: dict | None = None,
    revision_count: int = 0,
) -> NewsDraft:
    base = {
        "id": "n1",
        "title": "BTC ETF approved by SEC",
        "url": "https://example.com/n1",
        "source": "CoinDesk",
        "published_at": "2026-05-14T09:00:00+00:00",
        "summary": "Long summary text",
        "assets": ["BTC"],
        "category": "etf_institutional",
        "sector": "regulation_etf_institutional",
        "impact_score": 88.0,
    }
    if source_news_overrides:
        base.update(source_news_overrides)
    return NewsDraft(
        draft_id="d1",
        created_at="2026-05-14T10:00:00+00:00",
        status="pending_review",
        source_news=base,
        post_html="<b>orig post</b>",
        claude_json=claude_json or {"specific_title": "BTC ETF approved"},
        revision_count=revision_count,
    )
```

## Обязательные тесты

### Константы

1. **test_max_drafts_is_positive_int** — `isinstance(MAX_DRAFTS, int)`,
   `MAX_DRAFTS > 0`. (Точное значение не фиксируем — рост допустим.)

2. **test_regenerate_instruction_mentions_facts** — `"факт"` (substring)
   в `REGENERATE_INSTRUCTION.lower()`. Это инвариант: при regenerate
   мы не должны выдумывать новые факты.

3. **test_regenerate_instruction_mentions_url** — `"url"` в
   `REGENERATE_INSTRUCTION.lower()`. Инвариант: URL не меняем.

4. **test_regenerate_instruction_no_markdown_wrapper** — текст
   инструкции содержит требование "без markdown" / "json". Просто
   проверь что substring `"json"` или `"JSON"` есть в тексте.

5. **test_revise_instruction_mentions_facts** — `"факт"` в
   `REVISE_INSTRUCTION.lower()`.

6. **test_revise_instruction_forbids_signals** — REVISE_INSTRUCTION
   запрещает «сигналы» (substring `"сигнал"` в .lower()).

7. **test_revise_instruction_forbids_profit_promises** — substring
   `"прибыл"` в `REVISE_INSTRUCTION.lower()` (часть «обещаний прибыли»).

### _source_news_for_claude — edge cases

8. **test_source_news_includes_all_required_keys** — для базового
   draft результат содержит keys:
   `{"id", "title", "url", "source", "published_at", "summary",
   "assets", "category", "sector", "impact_score"}`.

9. **test_source_news_summary_under_400_unchanged** — summary длиной
   100 символов. Результат: `result["summary"]` равен исходной строке.

10. **test_source_news_summary_at_exactly_400_unchanged** — summary
    ровно 400 символов. Не обрезается.

11. **test_source_news_summary_over_400_truncated** — summary 500
    символов. `len(result["summary"]) == 400`.

12. **test_source_news_empty_summary_returns_empty_string** —
    `source_news.summary = ""`. `result["summary"] == ""`.

13. **test_source_news_missing_summary_returns_empty_string** —
    draft с `source_news` БЕЗ ключа `"summary"`. `result["summary"]
    == ""` (защита от None/missing).

14. **test_source_news_missing_assets_returns_empty_list** — без
    ключа `"assets"`. `result["assets"] == []`.

15. **test_source_news_impact_score_zero_when_missing** —
    `source_news` без `"impact_score"`. `result["impact_score"] == 0`.

16. **test_source_news_impact_score_zero_when_none** —
    `source_news["impact_score"] = None`. `result["impact_score"] == 0`.

17. **test_source_news_preserves_assets_list** — assets `["BTC", "ETH"]`
    в source_news → `result["assets"] == ["BTC", "ETH"]`.

18. **test_source_news_preserves_url_unchanged** — URL не модифицируется.

### NewsDraft revision_count

19. **test_news_draft_revision_count_default_zero** — `NewsDraft(...)`
    без revision_count → 0.

20. **test_news_draft_revision_count_increment_via_dataclass** —
    `draft.revision_count = 3`; `assert draft.revision_count == 3`.
    (Не immutable dataclass, можно мутировать.)

## Что НЕ делать

- НЕ вызывай `regenerate_payload()` / `revise_payload()` / `_ask_claude()` —
  они идут к Anthropic.
- Не моки Anthropic.
- Не пиши `if __name__ == "__main__"`.

## Финальный ответ

Один Python-блок ```python ... ``` готового файла. Без пояснений.
