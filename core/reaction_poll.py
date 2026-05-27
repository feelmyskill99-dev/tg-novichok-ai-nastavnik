"""Stage 14f — встроенные «реакция-опросы» в постах.

Подсмотрено у @cryptodaily (см. outputs/cryptodaily_sample.json):

    Ждете рост летом или падение ниже $60k?
    🔥 – Лету быть зеленым
    👀 – Сначала обновим минимум

Подписчик голосует **нативной реакцией** Telegram (long-press на пост, выбор
эмодзи). post_engagement handler уже агрегирует распределение реакций
(Stage feat-post-reactions-v2). Эта механика — просто видимый CTA в посте,
который объясняет читателю что 🔥 и 👀 означают.

Контракт:
- `build_poll_block(question, options) -> str` собирает HTML-блок.
- `options` — list[(emoji, short_text)], 2-4 элемента.
- Возвращает строку готовую к подклейке снизу к существующему посту.

Использование (из morning_briefing/author_notes/etc):
    poll = build_poll_block(
        "Ждёте отскок или ниже?",
        [("🔥", "отскок"), ("👀", "ниже")],
    )
    full_html = main_post_html + "\\n\\n" + poll
"""
from __future__ import annotations

from html import escape as _esc

MIN_OPTIONS = 2
MAX_OPTIONS = 4
MAX_QUESTION_LEN = 120
MAX_OPTION_LEN = 60


def build_poll_block(question: str, options: list[tuple[str, str]]) -> str:
    """Собрать HTML-блок встроенного reaction-опроса.

    question — короткий вопрос (≤120 chars, иначе обрезается).
    options — [(emoji, текст), ...] 2-4 пары.

    Если options меньше 2 или больше 4 — возвращаем пустую строку
    (caller тогда не подключает блок).

    Пустой question → пустая строка.

    HTML-escape применяется к question/текстам. Emoji не escape'ится
    (они в Telegram передаются как unicode-символы).
    """
    q = (question or "").strip()
    if not q:
        return ""
    if not options or len(options) < MIN_OPTIONS or len(options) > MAX_OPTIONS:
        return ""

    if len(q) > MAX_QUESTION_LEN:
        q = q[:MAX_QUESTION_LEN - 1].rstrip() + "…"

    lines: list[str] = [f"<i>{_esc(q, quote=False)}</i>"]
    for entry in options:
        if not isinstance(entry, (tuple, list)) or len(entry) != 2:
            continue
        emoji, text = entry
        emoji = (emoji or "").strip()
        text = (text or "").strip()
        if not emoji or not text:
            continue
        if len(text) > MAX_OPTION_LEN:
            text = text[:MAX_OPTION_LEN - 1].rstrip() + "…"
        lines.append(f"{emoji} — {_esc(text, quote=False)}")

    if len(lines) < MIN_OPTIONS + 1:
        return ""

    return "\n".join(lines)


# Готовые шаблоны опросов для разных post_type'ов. Caller'у не обязательно
# их использовать, но это удобная отправная точка.

MORNING_POLLS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Как думаешь, BTC сегодня?",
        [("🔥", "вверх к новым максимумам"), ("👀", "коррекция продолжится")],
    ),
    (
        "Что важнее на этой неделе?",
        [("📊", "макро-данные"), ("📰", "новости регуляторов"), ("🐳", "движения китов")],
    ),
    (
        "Заходишь сейчас в BTC?",
        [("🔥", "докупаю"), ("👀", "жду уровень"), ("🤝", "не торгую вообще")],
    ),
]


def pick_morning_poll(now_iso: str = "") -> tuple[str, list[tuple[str, str]]]:
    """Детерминированный выбор морнинг-опроса по дате (чтобы один и тот же
    опрос не выпадал два дня подряд, но и тестируемо)."""
    if not MORNING_POLLS:
        return ("", [])
    # Простой ротатор по дню месяца / длина списка.
    idx = 0
    if now_iso:
        try:
            day = int(now_iso[8:10])
            idx = day % len(MORNING_POLLS)
        except (ValueError, IndexError):
            pass
    return MORNING_POLLS[idx]
