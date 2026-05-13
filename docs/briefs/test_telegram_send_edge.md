# Задача: tests/test_telegram_send_edge.py

## Цель

Граничные cases для `core.telegram_send.split_html_for_telegram`. Базовый
`tests/test_telegram_send.py` уже покрывает основной flow (9 тестов).
Здесь — edge cases и потенциальные баги.

## Правила

1. pytest. Без моков.
2. Без эмодзи в коде/комментариях.
3. Импорты:
   ```python
   import sys
   from pathlib import Path
   import pytest
   ROOT = Path(__file__).resolve().parent.parent
   sys.path.insert(0, str(ROOT))
   from core.telegram_send import split_html_for_telegram
   ```

## Контракт API

```python
def split_html_for_telegram(text: str, *, limit: int = 4096) -> list[str]:
```

Поведение:
- `text=""` или whitespace-only → `[]`
- `len(text) <= limit` → `[text]` (один кусок)
- Иначе режется по приоритету: `\n\n` → `\n` → пробел → safe break (hard cut)
- НЕ режет внутри открытого HTML-тега `<a>`, `<b>`, `<code>`, и т.п.
- Каждый кусок ≤ limit

## Обязательные тесты

### Граничные значения limit

1. **test_limit_one_char_returns_each_char** — `limit=1`, текст из 5
   символов. Не падает. Возвращает list, каждый кусок имеет длину 1.
   (Hard cut работает в fallback ветке.)

2. **test_very_small_limit_with_html** — `limit=10`, текст
   `'<b>hello world</b>'` (длина 18). Не падает. Куски ≤ 10 символов.
   Открытые `<b>` теги в одном куске должны иметь закрытие в том же.
   (Проверь: для каждого куска `c.count("<b>") == c.count("</b>")`.)

3. **test_limit_larger_than_text** — text="hello", `limit=100`.
   Возвращает `["hello"]`.

4. **test_zero_limit_does_not_infinite_loop** — `limit=0`. Не должен
   зависнуть навечно. Допустимо: вернуть `[text]` или поднять
   AssertionError или вернуть hard-cut на каждом символе. Главное —
   функция возвращается за разумное время (<1 сек).
   Если зависнет → KillTime exception сработает. Используй
   `@pytest.mark.timeout(...)` НЕТ — этот плагин не установлен.
   Вместо timeout — вызови функцию без обёртки; если она реально виснет,
   pytest сам зависнет в CI, но это видно сразу.
   Альтернативный safer вариант: пропустить через `pytest.skip` если
   `split_html_for_telegram` не имеет защиты от limit=0.
   САМОЕ ПРОСТОЕ: вызвать с limit=0 и убедиться что результат — list
   (любой). Если функция зависнет — тест не пройдёт по timeout pytest
   default. Не пиши никакого специального протекта.

### HTML-теги

5. **test_nested_tags_not_split_inside_outer** — текст
   `'<b><i>important</i></b>'` * N для длины >limit. После split:
   каждый кусок должен иметь сбалансированные `<b>...</b>` И `<i>...</i>`.
   Подсчёт: `c.count("<b>") == c.count("</b>")` и `c.count("<i>") == c.count("</i>")` для каждого куска.

6. **test_self_closing_like_tag_handled** — текст содержит `<br>` или
   `<hr>` (Telegram их не поддерживает, но функция не должна падать).
   Просто проверь что split не падает и возвращает list.

7. **test_html_entities_preserved** — текст содержит `&amp;`, `&lt;`,
   `&gt;`, `&quot;`. После split — все entities целы в каком-то из кусков
   (не разрезаны посередине).

### Whitespace

8. **test_text_with_only_newlines** — `text="\n\n\n\n"`. Должно быть `[]`
   (так как `text.strip()` пустой).

9. **test_text_with_tabs_only** — `text="\t\t\t"`. Должно быть `[]`.

10. **test_text_with_unicode_whitespace_only** — `text="    "` (4 пробела).
    Должно быть `[]`.

### Большие тексты

11. **test_30k_text_splits_into_8_or_more_chunks** — 30000 символов
    (паттерн `"abc " * 7500`). После split каждый chunk ≤ 4096, всего
    ≥ 8 кусков, сумма символов с учётом обрезанных пробелов ≥ 29000.

12. **test_huge_single_word_no_spaces** — текст из 6000 символов одного
    слова без пробелов и переносов (`"x" * 6000`). Должен hard-cut'ить.
    Не зависает, возвращает ≥ 2 куска ≤ 4096.

### Контракт возврата

13. **test_return_type_is_list_of_str** — `assert isinstance(result, list)`,
    `assert all(isinstance(c, str) for c in result)`.

14. **test_chunks_have_no_empty_strings** — для любого валидного входа
    результат не должен содержать `""` (пустые строки).

## Что НЕ делать

- Не моки.
- Не пиши `if __name__ == "__main__"`.
- Не используй `pytest.mark.timeout` (плагин не установлен).
- Не проверяй точную равность контента (split rstrip'ит — содержимое может
  отличаться от input по whitespace). Проверяй лишь длины кусков, баланс
  тегов, валидность типов.

## Финальный ответ

Один Python-блок ```python ... ``` готового файла. Без пояснений.
