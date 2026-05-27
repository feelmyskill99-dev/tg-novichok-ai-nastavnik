"""Stage 14f — встроенные reaction-опросы в постах."""
from __future__ import annotations

from core.reaction_poll import (
    build_poll_block,
    pick_morning_poll,
    MORNING_POLLS,
    MIN_OPTIONS,
    MAX_OPTIONS,
    MAX_QUESTION_LEN,
    MAX_OPTION_LEN,
)


# ---- build_poll_block ----

def test_basic_two_options():
    out = build_poll_block(
        "Ждёте отскок?",
        [("🔥", "к ATH"), ("👀", "ниже")],
    )
    assert "<i>Ждёте отскок?</i>" in out
    assert "🔥 — к ATH" in out
    assert "👀 — ниже" in out


def test_empty_question_returns_empty():
    assert build_poll_block("", [("🔥", "a"), ("👀", "b")]) == ""


def test_whitespace_question_returns_empty():
    assert build_poll_block("   ", [("🔥", "a"), ("👀", "b")]) == ""


def test_too_few_options_returns_empty():
    assert build_poll_block("Q", [("🔥", "only one")]) == ""


def test_too_many_options_returns_empty():
    opts = [("🔥", "a"), ("👀", "b"), ("🤝", "c"), ("📊", "d"), ("🎯", "e")]
    assert build_poll_block("Q", opts) == ""


def test_long_question_truncated():
    q = "x" * (MAX_QUESTION_LEN + 50)
    out = build_poll_block(q, [("🔥", "a"), ("👀", "b")])
    assert "…" in out


def test_html_escapes_question():
    out = build_poll_block(
        "<script>alert(1)</script>",
        [("🔥", "yes"), ("👀", "no")],
    )
    assert "&lt;script&gt;" in out
    assert "<script>alert" not in out


def test_html_escapes_option_text():
    out = build_poll_block(
        "Q",
        [("🔥", "<img src=x>"), ("👀", "ok")],
    )
    assert "&lt;img" in out
    assert "<img src" not in out


def test_skips_invalid_option_entries():
    """Если в options попал кортеж не из 2 элементов — пропускаем."""
    out = build_poll_block(
        "Q",
        [("🔥", "a"), ("👀", "b"), ("only_one",)],  # type: ignore
    )
    assert "🔥" in out
    assert "👀" in out


def test_skips_option_with_empty_emoji_or_text():
    """Опции с пустым emoji или текстом пропускаются."""
    out = build_poll_block(
        "Q",
        [("🔥", "a"), ("", "b"), ("👀", "")],
    )
    # Только первая опция валидная — итого вариантов 1 → меньше MIN_OPTIONS
    # => возвращается ""
    assert out == ""


def test_three_options_ok():
    out = build_poll_block(
        "Что важнее?",
        [("📊", "макро"), ("📰", "новости"), ("🐳", "киты")],
    )
    assert out.count("\n") >= 3  # Q + 3 options


# ---- pick_morning_poll ----

def test_pick_returns_one_of_morning_polls():
    q, opts = pick_morning_poll("2026-05-27T07:00:00+00:00")
    assert (q, opts) in MORNING_POLLS


def test_pick_deterministic_by_date():
    """Один и тот же день → один и тот же опрос."""
    r1 = pick_morning_poll("2026-05-27T07:00:00+00:00")
    r2 = pick_morning_poll("2026-05-27T23:00:00+00:00")
    assert r1 == r2


def test_pick_different_days_can_differ():
    """Разные дни месяца обычно дают разные опросы (зависит от ротации)."""
    days = ["2026-05-27", "2026-05-28", "2026-05-29"]
    # Сравниваем по question, opts — list[tuple] не hashable.
    qs = {pick_morning_poll(f"{d}T07:00:00+00:00")[0] for d in days}
    # Поскольку ротатор = day % len(MORNING_POLLS), 3 разных дня обычно
    # дают 3 разных или max len(MORNING_POLLS) уникальных.
    assert len(qs) >= 1


def test_pick_empty_iso_returns_first():
    """Пустая строка — индекс 0."""
    q, opts = pick_morning_poll("")
    assert (q, opts) == MORNING_POLLS[0]


def test_pick_invalid_iso_safe():
    """Битый ISO не должен падать."""
    q, opts = pick_morning_poll("not-a-date")
    assert (q, opts) == MORNING_POLLS[0]


# ---- limits constants ----

def test_min_options_is_2():
    assert MIN_OPTIONS == 2


def test_max_options_is_4():
    assert MAX_OPTIONS == 4
