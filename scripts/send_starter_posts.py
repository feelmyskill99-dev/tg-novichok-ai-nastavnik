"""Отправляет 5 стартовых постов канала в OWNER_CHAT_ID на ручную проверку.

В канал НЕ публикует. Используется только для approve-pipeline:
владелец читает в DM, потом сам решает, идёт ли пост в канал.

Посты 1–4 — статичный контент, написанный руками. Пост 5 (рыночный обзор с
графиком и AI-наставником) генерируется через `python bot.py --post-now` отдельно,
он использует Market + Claude + chart.
"""

from __future__ import annotations

import asyncio
import html as _html
import os
import sys
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv

import aiohttp
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=ROOT / ".env")


class _ThreadedResolverSession(AiohttpSession):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._connector_init["resolver"] = aiohttp.ThreadedResolver()


PARTNER_URL = (os.getenv("PARTNER_URL") or "").strip()
DISCLAIMER = (
    "Не является финансовым советом. Это личный дневник обучения, "
    "а AI-анализ носит ознакомительный характер."
)
DISCLAIMER_LIGHT = (
    "Не финсовет. Это личный дневник обучения, "
    "а AI-анализ носит ознакомительный характер."
)


def _e(s) -> str:
    return _html.escape("" if s is None else str(s), quote=False)


def _hashtags(*tags: str) -> str:
    return " ".join(_e(t if t.startswith("#") else f"#{t}") for t in tags)


def _wrap(text: str, *, dry_run_marker: bool = True) -> str:
    """Добавляет [DRY_RUN OWNER PREVIEW] маркер, чтобы владелец сразу видел: это превью."""
    if dry_run_marker:
        return "<i>[DRY_RUN OWNER PREVIEW]</i>\n\n" + text
    return text


# =============================================================================
# Тексты постов
# =============================================================================

def post_1_manifest() -> str:
    parts: list[str] = []
    parts.append("📌 <b>Дневник трейдера-новичка под надзором ИИ</b>")
    parts.append("")
    parts.append("Я начинаю с маленького депозита и веду этот канал, потому что хочу "
                 "учиться не на YouTube-обещаниях, а на собственных ошибках.")
    parts.append("")
    parts.append("Но с холодной головой рядом.")
    parts.append("")
    parts.append("Холодную голову одолжил у Claude 🤖")
    parts.append("")
    parts.append("<b>Что здесь будет:</b>")
    parts.append("— рыночные обзоры 2 раза в день;")
    parts.append("— разборы новостей, которые могут двигать рынок;")
    parts.append("— учебные paper-сделки и сделки с подтверждением;")
    parts.append("— ошибки новичка без прикрас;")
    parts.append("— риск-менеджмент простым языком;")
    parts.append("— честный лог того, как иногда страшно нажать Buy.")
    parts.append("")
    parts.append("<b>Чего здесь НЕ будет:</b>")
    parts.append("— «сигналов»;")
    parts.append("— «гарантированных входов»;")
    parts.append("— обещаний прибыли;")
    parts.append("— «киты точно покупают»;")
    parts.append("— ракет, бычков и Lambo.")
    parts.append("")
    parts.append("<b>Как работает канал:</b>")
    parts.append("")
    parts.append("😬 <b>Новичок — это я.</b>")
    parts.append("Пишу, что вижу, что чувствую и где внутренний хомяк уже тянется к кнопке.")
    parts.append("")
    parts.append("🤖 <b>AI-наставник — холодная часть.</b>")
    parts.append("Он объясняет, где риск, где шум, где FOMO, а где я просто пытаюсь "
                 "убедить себя, что «ну тут же очевидно».")
    parts.append("")
    parts.append("Этот формат не делает меня умнее рынка.")
    parts.append("Он просто заставляет думать перед сделкой.")
    if PARTNER_URL:
        parts.append("")
        parts.append("Графики и сделки разбираю на Gate.io — там у меня стартовая "
                     "точка и маленький депозит:")
        parts.append("")
        parts.append(f"<a href=\"{_e(PARTNER_URL)}\">{_e(PARTNER_URL)}</a>")
    parts.append("")
    parts.append(f"<i>{_e(DISCLAIMER_LIGHT)}</i>")
    parts.append("")
    parts.append(_hashtags("честный_путь", "новичок", "риск_менеджмент", "база_знаний"))
    return "\n".join(parts)


def post_2_how_to_read() -> str:
    parts: list[str] = []
    parts.append("📖 <b>Как читать этот дневник</b>")
    parts.append("")
    parts.append("Каждый пост — это не сигнал и не инструкция «что покупать».")
    parts.append("")
    parts.append("Это разбор ситуации глазами новичка и холодная проверка "
                 "от AI-наставника.")
    parts.append("")
    parts.append("Обычно пост состоит из трёх частей:")
    parts.append("")
    parts.append("😬 <b>Мысли новичка</b>")
    parts.append("")
    parts.append("Это я.")
    parts.append("")
    parts.append("Что вижу на графике.")
    parts.append("Что чувствую.")
    parts.append("Чего хочется сделать.")
    parts.append("")
    parts.append("Иногда хочется зайти в шорт просто потому, что всё красное.")
    parts.append("Иногда хочется купить зелёную свечу, потому что «поезд уходит».")
    parts.append("")
    parts.append("Вот в такие моменты новичков обычно и ловят.")
    parts.append("")
    parts.append("🤖 <b>AI-наставник</b>")
    parts.append("")
    parts.append("Холодный разбор.")
    parts.append("")
    parts.append("Где риск.")
    parts.append("Где FOMO.")
    parts.append("Где плохое соотношение риск/прибыль.")
    parts.append("Где новость громкая, но сделки всё равно нет.")
    parts.append("")
    parts.append("Без эмоций, без «кубков прибыли» и без желания доказать рынку, "
                 "что я умнее свечки.")
    parts.append("")
    parts.append("📌 <b>Вывод</b>")
    parts.append("")
    parts.append("1–2 короткие мысли.")
    parts.append("")
    parts.append("Не сигнал.")
    parts.append("Не призыв к действию.")
    parts.append("Просто запись в дневник: какую ошибку сегодня удалось заметить.")
    parts.append("")
    parts.append("<b>Что НЕ путать:</b>")
    parts.append("— «новичок хочет зайти» ≠ «надо зайти»;")
    parts.append("— «AI видит риск» ≠ «AI советует продавать»;")
    parts.append("— «разбор сделки» ≠ «повтори сделку»;")
    parts.append("— «интересная новость» ≠ «торговый план».")
    parts.append("")
    parts.append("Если хочешь читать этот канал с пользой, задавай себе один вопрос:")
    parts.append("")
    parts.append("🐹 <i>Что бы здесь сделал внутренний хомяк — и как бы его "
                 "остановил наставник?</i>")
    parts.append("")
    parts.append(f"<i>{_e(DISCLAIMER_LIGHT)}</i>")
    parts.append("")
    parts.append(_hashtags("база_знаний", "честный_путь", "ошибки_новичка"))
    return "\n".join(parts)


def post_3_why_no_x20() -> str:
    parts: list[str] = []
    parts.append("⚖️ <b>Почему я не начинаю с фьючерсов x20</b>")
    parts.append("")
    parts.append("😬 <b>Мысли новичка</b>")
    parts.append("Депозит маленький, хочется быстрее. Открыл фьючерсы, увидел плечо x20, "
                 "и внутренний хомяк уже считает «было 50, станет 1000».")
    parts.append("")
    parts.append("🤖 <b>AI-наставник</b>")
    parts.append("Простая математика, без лозунгов.")
    parts.append("")
    parts.append("Плечо x20 значит: при движении цены против тебя на 5% — твой депозит "
                 "ликвидируется. На 4% — просто почти весь.")
    parts.append("")
    parts.append("BTC спокойно ходит на 3–5% за час даже без новостей. Это не «волатильность "
                 "выросла», это нормальный вторник.")
    parts.append("")
    parts.append("На реальном маленьком депозите x20 — это не «больше прибыли», это "
                 "«быстрее закончится». Большинство новичков сливают первые депо в первые "
                 "дни именно так. Не потому что не угадали направление, а потому что "
                 "стоп-лосс при таком плече стоит на расстоянии чиха.")
    parts.append("")
    parts.append("⚠️ <b>Ошибка новичка</b>")
    parts.append("Думать, что «плечо = ускоритель прибыли». На самом деле плечо — это "
                 "ускоритель <b>ошибки</b>. Прибыль или убыток — оба ускоряются одинаково, "
                 "только убыток нельзя отменить.")
    parts.append("")
    parts.append("📌 <b>Вывод</b>")
    parts.append("Маленькое плечо на маленьком депозите — это не страх, это здравый смысл. "
                 "Здесь учимся выживать, а не «удваивать за неделю».")
    parts.append("")
    parts.append(f"<i>{_e(DISCLAIMER)}</i>")
    parts.append("")
    parts.append(_hashtags("риск_менеджмент", "ошибки_новичка", "база_знаний", "плечо"))
    return "\n".join(parts)


def post_4_risk_per_trade() -> str:
    parts: list[str] = []
    parts.append("🛡 <b>Что такое «риск на сделку» простыми словами</b>")
    parts.append("")
    parts.append("😬 <b>Мысли новичка</b>")
    parts.append("Все говорят «не рискуй больше 1–2% от депозита на сделку». Что это вообще "
                 "значит, если у меня всего 50 USDT?")
    parts.append("")
    parts.append("🤖 <b>AI-наставник</b>")
    parts.append("Это значит вот что. Перед сделкой ты спрашиваешь: «сколько денег я готов "
                 "потерять, если стоп-лосс сработает?»")
    parts.append("")
    parts.append("Пример. Депозит 50 USDT, риск на сделку 0.2%. Это 0.10 USDT — десять центов. "
                 "Кажется, что это смешно. Но это значит, что 50 подряд проигранных сделок "
                 "не убьют депозит. И это уже неплохая страховка.")
    parts.append("")
    parts.append("Дальше считаем. Если стоп стоит на 1% ниже входа, размер позиции "
                 "получается такой, чтобы при касании стопа потерять ровно эти 10 центов. "
                 "Это и есть «риск на сделку».")
    parts.append("")
    parts.append("Что важно:")
    parts.append("— стоп-лосс ставится <b>до</b> входа, а не «когда станет страшно»;")
    parts.append("— размер позиции считается <b>от стопа</b>, а не «сколько хочется»;")
    parts.append("— подвинуть стоп после входа «дать рынку шанс» — это уже не сделка, "
                 "это лотерея.")
    parts.append("")
    parts.append("⚠️ <b>Ошибка новичка</b>")
    parts.append("Считать риск «на глаз»: открыть на «весь депозит», потом нервно следить "
                 "за свечами. Это не торговля, это скейтборд без шлема.")
    parts.append("")
    parts.append("📌 <b>Вывод</b>")
    parts.append("Сначала считаешь риск, потом ищешь сделку. Не наоборот.")
    parts.append("")
    parts.append(f"<i>{_e(DISCLAIMER)}</i>")
    parts.append("")
    parts.append(_hashtags("риск_менеджмент", "база_знаний", "ошибки_новичка", "стоп_лосс"))
    return "\n".join(parts)


# =============================================================================
# Дополнительно — текст «оформления»: имя, описание, закреп — для удобства владельца
# =============================================================================

def channel_branding_text() -> str:
    return (
        "📦 <b>[CHANNEL BRANDING — для ручной установки]</b>\n"
        "\n"
        "<b>Название:</b>\n"
        "Депозит под надзором ИИ\n"
        "\n"
        "<b>Описание (Telegram → Edit channel → Description):</b>\n"
        "Честный дневник трейдера-новичка под надзором ИИ 🤖\n\n"
        "Маленький депозит, ошибки без прикрас, риск-менеджмент, новости и "
        "внутренний хомяк 🐹\n\n"
        "Без сигналов, гуру и обещаний прибыли.\n"
        "\n"
        "<b>Закреп №1 (манифест):</b> Пост 1 — закрепи его после публикации.\n"
        "<b>Закреп №2 (как читать дневник):</b> Пост 2 — закрепи поверх первого "
        "(в Telegram можно пинить несколько сообщений).\n"
        "\n"
        "<b>Аватар:</b> файл <code>outputs/images/channel_avatar.png</code>, "
        "установить вручную через Settings → Edit channel → Photo."
    )


# =============================================================================
# Отправка
# =============================================================================

async def _send_owner(posts: Iterable[tuple[str, str]]) -> None:
    token = (os.getenv("TELEGRAM_TOKEN") or "").strip()
    owner = (os.getenv("OWNER_CHAT_ID") or "").strip()
    if not token or not owner:
        print("TELEGRAM_TOKEN или OWNER_CHAT_ID пустые", file=sys.stderr)
        return
    bot = Bot(token=token, session=_ThreadedResolverSession())
    try:
        for label, text in posts:
            print(f"-> sending: {label}")
            await bot.send_message(owner, _wrap(text), parse_mode=ParseMode.HTML,
                                   disable_web_page_preview=False)
            # пауза между сообщениями, чтобы Telegram не зажал rate limit
            await asyncio.sleep(1.2)
    finally:
        await bot.session.close()


def main() -> int:
    posts = [
        ("BRANDING", channel_branding_text()),
        ("Post 1: Manifest (use as pinned)", post_1_manifest()),
        ("Post 2: Как читать дневник", post_2_how_to_read()),
        ("Post 3: Почему не фьючерсы x20", post_3_why_no_x20()),
        ("Post 4: Риск на сделку", post_4_risk_per_trade()),
    ]
    asyncio.run(_send_owner(posts))
    print()
    print("Готово. Пост 5 (рыночный обзор + график + AI-наставник) — отдельно через")
    print("    python bot.py --post-now")
    return 0


if __name__ == "__main__":
    sys.exit(main())
