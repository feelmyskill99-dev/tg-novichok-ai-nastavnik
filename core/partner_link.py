"""partner_link — добавляет UTM-метки к PARTNER_URL для трекинга трафика.

Все ссылки на партнёра (Gate.io) идут через build_partner_url() — она
дописывает utm_source=tg_ai_deposit, utm_medium=<post_type> и опц.
utm_content=<post_id>. Так в Gate.io можно понимать какой тип поста
конвертит лучше.

Сохраняет уже существующие query-параметры PARTNER_URL (например, ref-id).

PARTNER_HOOKS — список fraz, в которые вставляется ссылка. Ротируется
по индексу post_num в bot.build_post_html, чтобы не вылезала одна и та
же подводка трижды в день.
"""

from __future__ import annotations

from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl


UTM_SOURCE = "tg_ai_deposit"

PARTNER_HOOKS = [
    'Графики и сделки разбираю через биржу, где сам учусь: <a href="{url}">площадка</a>',
    'Я тестирую инструменты здесь: <a href="{url}">площадка</a>',
    'Где смотрю фандинг и OHLCV: <a href="{url}">площадка</a>',
]


def build_partner_url(
    base_url: str,
    *,
    post_type: str = "post",
    post_id: str | None = None,
) -> str:
    """Возвращает base_url с UTM-параметрами. Если base_url пустой — пустую строку.

    Параметры UTM:
    - utm_source = tg_ai_deposit (фиксировано)
    - utm_medium = post_type (market / news / education / author_note / pinned / weekly_diary)
    - utm_content = post_id (если задан) — для пер-постового трекинга

    Существующие query-параметры (например, ref=XXX из реф-ссылки Gate.io)
    сохраняются. UTM-параметры с тем же ключом перезаписываются (это позволяет
    обновлять метку у уже-помеченной ссылки без двойного знака ?).
    """
    base_url = (base_url or "").strip()
    if not base_url:
        return ""

    parsed = urlparse(base_url)
    existing_qs = dict(parse_qsl(parsed.query, keep_blank_values=True))

    existing_qs["utm_source"] = UTM_SOURCE
    existing_qs["utm_medium"] = post_type or "post"
    if post_id:
        existing_qs["utm_content"] = post_id

    new_query = urlencode(existing_qs)
    return urlunparse((
        parsed.scheme, parsed.netloc, parsed.path,
        parsed.params, new_query, parsed.fragment,
    ))
