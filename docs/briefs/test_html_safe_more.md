# Задача: tests/test_html_safe_more.py

## Цель

Дополнительные edge-tests для `core.html_safe`. Базовый
`tests/test_html_safe.py` (19 тестов) покрывает основной flow.
Здесь — XSS-vectors, broken HTML, Unicode, real-world data.

## Правила

1. pytest. Без моков.
2. Без эмодзи.
3. Импорты:
   ```python
   import sys
   from pathlib import Path
   import pytest
   ROOT = Path(__file__).resolve().parent.parent
   sys.path.insert(0, str(ROOT))
   from core.html_safe import escape_html, sanitize_telegram_html
   ```

## Контракт

```python
escape_html(value: Any) -> str
sanitize_telegram_html(raw: str) -> str
```

Allowlist для sanitize: `b, strong, i, em, code, pre, u, s, a` (с http(s)
href). Остальное → escape. `<a>` без href или с javascript: → тег
выпиливается, текст остаётся.

## Обязательные тесты

### escape_html

1. **test_escape_html_with_float_value** — `escape_html(3.14)` → `"3.14"`.
2. **test_escape_html_with_bool** — `escape_html(True)` → `"True"`,
   `escape_html(False)` → `"False"`.
3. **test_escape_html_with_list_coerces_via_str** — `escape_html([1, 2])`
   → `"[1, 2]"`.
4. **test_escape_html_with_dict** — `escape_html({"a": 1})` → str
   представление (содержит `"a": 1`).
5. **test_escape_html_only_amp_lt_gt_escaped** — `escape_html("&<>")` →
   `"&amp;&lt;&gt;"`. Двойные кавычки и одинарные — НЕ трогаем
   (quote=False).
6. **test_escape_html_unicode_preserved** — `escape_html("привет мир 🌍")`
   → `"привет мир 🌍"` (как есть).
7. **test_escape_html_newlines_preserved** — `escape_html("a\nb")` →
   `"a\nb"` (HTML-escape не трогает \n).

### sanitize_telegram_html — XSS vectors

8. **test_sanitize_data_uri_href_dropped** —
   `'<a href="data:text/html,...">x</a>'`. Тег выпиливается, "x" остаётся,
   "data:" не появляется в выводе как href.
9. **test_sanitize_relative_href_dropped** —
   `'<a href="/path">x</a>'`. Относительный URL — не http/https → drop.
10. **test_sanitize_uppercase_javascript_dropped** —
    `'<a href="JavaScript:alert(1)">x</a>'`. Case-insensitive check
    на scheme — должен drop'ать. ВНИМАНИЕ: реальный код проверяет
    `href.startswith("http://")` / `http**s**://` (lowercase). Если
    "JavaScript:" не начинается с этих префиксов, тег выпадает —
    проверим именно поведение: тег НЕ остаётся.
11. **test_sanitize_with_no_quotes_around_href_dropped** —
    `'<a href=https://x.com>y</a>'`. В regex есть требование двойных
    кавычек, так что href БЕЗ кавычек не парсится → тег drop.
12. **test_sanitize_a_with_single_quotes_href_dropped** —
    `"<a href='https://x.com'>y</a>"`. Тоже не парсится regex'ом → drop.

### sanitize_telegram_html — broken HTML

13. **test_sanitize_unclosed_tag** —
    `"<b>missing close"`. Открыта `<b>`, закрытия нет. Должен
    проскочить через regex как `<b>` (allowed), текст следует,
    без exception.
14. **test_sanitize_only_opening_angle** — `"a < b"`. `<` + space → не
    тег → escape. Результат: `"a &lt; b"`.
15. **test_sanitize_malformed_attribute** —
    `'<b class="oops>text</b>'`. Сломан HTML. Не должен падать,
    результат — какой-то валидный string.

### sanitize_telegram_html — nested

16. **test_sanitize_b_inside_i_preserves_both** —
    `"<i><b>nested</b></i>"`. Оба разрешённых тега должны сохраниться.
17. **test_sanitize_disallowed_inside_allowed_escaped** —
    `"<b><script>alert(1)</script></b>"`. `<b>` сохраняется,
    `<script>` escape'ится → `"<b>&lt;script&gt;alert(1)&lt;/script&gt;</b>"`
    (или похожее).
18. **test_sanitize_self_closing_br_escaped** — `"<br>"`. `br` не в
    allowlist → escape → `"&lt;br&gt;"`.

### sanitize_telegram_html — Unicode + edge

19. **test_sanitize_preserves_emoji_text** —
    `"<b>Привет 🐹</b>"` → должен содержать `"<b>Привет 🐹</b>"`.
20. **test_sanitize_only_whitespace_returns_empty_or_whitespace** —
    `"   "` (4 пробела). Не падает, возвращает строку (точное значение
    не фиксируем — может быть `""` после strip или `"   "` без).
    Главное — не exception.

### sanitize_telegram_html — None / non-string

21. **test_sanitize_empty_returns_empty** — `sanitize_telegram_html("")`
    → `""`.

## Что НЕ делать

- Не моки.
- Не пиши `if __name__ == "__main__"`.

## Финальный ответ

Один Python-блок ```python ... ``` готового файла. Без пояснений.
