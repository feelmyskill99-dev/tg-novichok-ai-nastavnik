"""Telegram long-message guard (этап 1.3).

`split_html_for_telegram(text, limit)` режет HTML-строку на куски ≤limit,
не разрывая открытые HTML-теги вида `<a>...</a>`, `<b>...</b>`, `<code>...</code>`.

Алгоритм:
1. Если text ≤ limit — вернуть [text] как есть.
2. Иначе пытаемся резать по `\n\n` (абзацы).
3. Если один абзац > limit — режем по `\n`.
4. Если одна строка > limit — режем по пробелу.
5. Внутри пары `<a ...>...</a>` (и аналогичных) реза не происходит:
   границу куска сдвигаем влево к последней «безопасной» точке (вне открытого тега).
"""
from __future__ import annotations

import re

_OPEN_TAG_RE = re.compile(r"<([a-zA-Z][^/>\s]*)\b[^>]*>")
_CLOSE_TAG_RE = re.compile(r"</([a-zA-Z][^/>\s]*)\s*>")


def _safe_break_index(text: str, limit: int) -> int:
    """Найти максимально близкий к `limit` индекс, который НЕ внутри открытого HTML-тега.

    Возвращает индекс — позиция, ДО которой можно резать (т.е. `text[:i]` — кусок).
    Гарантируется i <= limit, i > 0 (по возможности).
    """
    if limit >= len(text):
        return len(text)

    candidate = limit
    while candidate > 0:
        prefix = text[:candidate]
        opens = len(_OPEN_TAG_RE.findall(prefix))
        closes = len(_CLOSE_TAG_RE.findall(prefix))
        if opens == closes:
            return candidate
        candidate -= 1
    return limit


def _split_one(text: str, limit: int) -> tuple[str, str]:
    """Отрезает один кусок ≤limit, возвращает (chunk, remainder)."""
    if len(text) <= limit:
        return text, ""

    # 1) попробуем по двойному \n
    cut = text.rfind("\n\n", 0, limit + 1)
    if cut <= 0:
        # 2) по одинарному
        cut = text.rfind("\n", 0, limit + 1)
    if cut <= 0:
        # 3) по пробелу
        cut = text.rfind(" ", 0, limit + 1)
    if cut <= 0:
        # 4) hard cut на лимите (НО — учтём, чтобы не разрезать тег)
        cut = _safe_break_index(text, limit)
        if cut <= 0:
            cut = limit

    # cut — позиция начала разделителя; не разрешим разрезать открытый тег.
    safe = _safe_break_index(text, cut)
    if safe <= 0:
        safe = cut

    chunk = text[:safe].rstrip()
    remainder = text[safe:].lstrip("\n ")
    return chunk, remainder


def split_html_for_telegram(text: str, *, limit: int = 4096) -> list[str]:
    """Разрезать HTML-text на ≤limit-кусков, не разрезая открытые HTML-теги."""
    if not text or not text.strip():
        return []
    text = text.strip()

    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        chunk, remaining = _split_one(remaining, limit)
        if not chunk:
            chunks.append(remaining[:limit])
            remaining = remaining[limit:].lstrip()
            continue
        chunks.append(chunk)
    return chunks
