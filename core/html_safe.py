"""HTML-safe helpers для Telegram-постов (этап 2.4 шаг 3).

`escape_html(s)` — простой HTML-escape с `quote=False`, превращает
None в "". Аналог bot.esc.

`sanitize_telegram_html(raw)` — allowlist Telegram-tags
(b/strong/i/em/u/s/code/pre/a с http(s) href). Раньше жил в admin_panel.py.

Зачем разделение:
- escape_html — для построения постов из Claude-payload (мы знаем где \\
  должен быть escape, а где наоборот HTML-тег)
- sanitize_telegram_html — для НЕДОВЕРЕННОГО ввода (admin draft, форма)
"""
from __future__ import annotations

import html as _html
import re
from typing import Any


def escape_html(value: Any) -> str:
    """HTML-escape с quote=False, None → пустая строка."""
    if value is None:
        return ""
    return _html.escape(str(value), quote=False)


# ---- allowlist sanitizer (бывший admin_panel.sanitize_telegram_html) ----

_ALLOWED_TAGS = frozenset({
    "b", "strong", "i", "em", "code", "pre", "u", "s",
})
_TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)\b([^>]*)>")
_A_HREF_RE = re.compile(r'href\s*=\s*"([^"]+)"', re.IGNORECASE)


def sanitize_telegram_html(raw: str) -> str:
    """Allowlist Telegram-tags. Всё прочее — escape.

    Telegram parse_mode=HTML поддерживает: b, strong, i, em, u, s, code, pre,
    a (с href). Остальные теги (включая <script>) экранируются.
    href должен быть http:// или https:// — иначе тег удаляется (текст сохраняется).
    """
    if not raw:
        return ""

    out: list[str] = []
    pos = 0
    for m in _TAG_RE.finditer(raw):
        out.append(_html.escape(raw[pos:m.start()], quote=False))
        slash, tag, attrs = m.group(1), m.group(2).lower(), m.group(3)
        if tag == "a":
            href_m = _A_HREF_RE.search(attrs)
            href = href_m.group(1) if href_m else ""
            if slash:
                out.append("</a>")
            elif href and (href.startswith("http://") or href.startswith("https://")):
                safe_href = _html.escape(href, quote=True)
                out.append(f'<a href="{safe_href}">')
            else:
                # битый/опасный href — теряем тег, оставляем текст
                pass
        elif tag in _ALLOWED_TAGS:
            out.append(f"</{tag}>" if slash else f"<{tag}>")
        else:
            # неизвестный тег — экранируем как текст
            out.append(_html.escape(m.group(0), quote=False))
        pos = m.end()
    out.append(_html.escape(raw[pos:], quote=False))
    return "".join(out)
