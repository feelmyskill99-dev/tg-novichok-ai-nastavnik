"""Этап 1.4: Publisher не должен зависеть от глобального mistake_tracker.

При `python bot.py --post-now` без scheduler-инициализации глобал mistake_tracker
остаётся None, и fallback-ветка `Publisher.publish()` падает с AttributeError.

Тесты на уровне исходника bot.py — проверяют, что:
- Publisher.__init__ инициализирует self.mistake_tracker
- Publisher.publish() использует self.mistake_tracker, а не глобал
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOT_PY = ROOT / "bot.py"


def _publisher_class_source() -> str:
    """Вырезает текст класса Publisher из bot.py."""
    text = BOT_PY.read_text(encoding="utf-8")
    m = re.search(r"^class Publisher:\n", text, re.MULTILINE)
    assert m, "class Publisher не найден в bot.py"
    start = m.start()
    # ищем следующий top-level `class ` или `async def ` или `def ` (на уровне 0)
    rest = text[m.end():]
    end_m = re.search(r"^(class |async def |def )", rest, re.MULTILINE)
    if end_m:
        return text[start: m.end() + end_m.start()]
    return text[start:]


def test_publisher_init_creates_mistake_tracker():
    src = _publisher_class_source()
    init_match = re.search(r"def __init__\(self.*?\):\n(.*?)(?=\n    [a-zA-Z@]|\Z)", src, re.DOTALL)
    assert init_match, "Publisher.__init__ не найден"
    init_body = init_match.group(1)

    assert "self.mistake_tracker" in init_body, (
        "Publisher.__init__ должен инициализировать self.mistake_tracker "
        "(этап 1.4: убрать зависимость от глобала)"
    )
    assert "MistakeTracker(" in init_body, (
        "Publisher.__init__ должен создавать MistakeTracker(...) локально"
    )


def test_publish_uses_self_mistake_tracker_not_global():
    src = _publisher_class_source()
    publish_match = re.search(
        r"async def publish\(.*?\n(.*?)(?=\n    [a-zA-Z@]|\Z)",
        src, re.DOTALL,
    )
    assert publish_match, "Publisher.publish не найден"
    body = publish_match.group(1)

    # Не должно быть прямого обращения к глобалу `mistake_tracker.`
    # (только через self.mistake_tracker)
    bare_calls = re.findall(r"(?<!self\.)\bmistake_tracker\.", body)
    assert not bare_calls, (
        f"Publisher.publish() обращается к глобалу mistake_tracker: {bare_calls}. "
        f"Должно быть self.mistake_tracker (этап 1.4)"
    )
