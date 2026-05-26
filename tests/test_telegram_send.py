"""Telegram long-message guard (этап 1.3 рефакторинга).

`split_html_for_telegram(text, limit)` режет строку на ≤limit-кусков по
безопасным границам (двойной перенос → одинарный → пробел), без обрыва
HTML-тегов вида `<a>...</a>`, `<b>...</b>`, `<code>...</code>`.

Helper НЕ балансирует произвольный вложенный HTML — лишь не режет внутри
открытого тега. Telegram parse_mode=HTML это и так требует.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.telegram_send import split_html_for_telegram


def test_short_text_returns_single_chunk():
    chunks = split_html_for_telegram("hello world", limit=4096)

    assert chunks == ["hello world"]


def test_exactly_at_limit_returns_single_chunk():
    text = "a" * 4096
    chunks = split_html_for_telegram(text, limit=4096)

    assert chunks == [text]


def test_splits_long_text_by_double_newline():
    para = "x" * 2000
    text = "\n\n".join([para, para, para])
    chunks = split_html_for_telegram(text, limit=4096)

    assert all(len(c) <= 4096 for c in chunks)
    assert len(chunks) >= 2
    # Содержимое сохраняется (с точностью до schema-нейтральной нормализации whitespace).
    rejoined = "\n\n".join(chunks)
    assert para in rejoined and rejoined.count(para) == 3


def test_split_does_not_cut_inside_a_tag():
    # Конструируем сценарий: 4080 символов мусора, потом длинный <a href="...">.
    prefix = "a" * 4080
    link = '<a href="https://example.com/very/long/url/that/extends">click</a>'
    text = prefix + "\n\n" + link + "\n\n" + "tail"

    chunks = split_html_for_telegram(text, limit=4096)

    for c in chunks:
        # Если открывается <a — закрывается тут же.
        opens = c.count("<a ")
        closes = c.count("</a>")
        assert opens == closes, f"Tag mismatch in chunk: opens={opens} closes={closes}"


def test_single_huge_paragraph_split_by_single_newline():
    # Один абзац длиннее лимита — режется по \n.
    line = "y" * 2000
    text = "\n".join([line, line, line])
    chunks = split_html_for_telegram(text, limit=4096)

    assert all(len(c) <= 4096 for c in chunks)
    assert len(chunks) >= 1


def test_single_huge_line_split_by_space():
    # Длинная строка без \n — режется по пробелу.
    text = " ".join(["word"] * 1500)  # ≈ 7500 chars
    chunks = split_html_for_telegram(text, limit=4096)

    assert all(len(c) <= 4096 for c in chunks)
    assert " ".join(chunks).count("word") == 1500


def test_no_chunk_exceeds_limit_for_4096():
    # Стресс-тест на 9000 chars — должно влезть в ≤3 куска, ни один не >4096.
    paragraph = "lorem ipsum " * 50  # ~600 chars
    text = "\n\n".join([paragraph] * 15)  # ~9000 chars
    chunks = split_html_for_telegram(text, limit=4096)

    assert all(len(c) <= 4096 for c in chunks)
    assert sum(len(c) for c in chunks) >= 9000 - 100  # допускаем потерю склейки \n


def test_empty_string_returns_empty_list():
    assert split_html_for_telegram("", limit=4096) == []


def test_whitespace_only_returns_empty_list():
    assert split_html_for_telegram("   \n\n  ", limit=4096) == []
