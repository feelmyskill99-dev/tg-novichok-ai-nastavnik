"""NewsPublisher — собирает HTML-сообщение из Claude-ответа и решает, куда слать.

Stage 12b: единый строгий формат поста (specific_title → Коротко → Главные моменты →
Почему это важно → 🐹 Мысль новичка → 🤖 AI-наставник → ⚠️ Ошибка новичка → 📌 Вывод
→ disclaimer → hashtags). Никаких generic-заголовков. Если specific_title пустой
или попадает в чёрный список — публикация блокируется publish_guard'ом.

Публикует в канал только если:
    ENABLE_NEWS=true
    NEWS_PUBLISH_TO_CHANNEL=true
    NEWS_DRY_RUN=false
    impact_score >= NEWS_MIN_IMPACT_SCORE
    payload прошёл validate_payload_for_publish()
    новость не дубликат
    лимит NEWS_MAX_POSTS_PER_DAY не превышен

Во всех остальных случаях (и по умолчанию) — отправляет только в OWNER_CHAT_ID.
"""

from __future__ import annotations

import hashlib
import html
import json
import logging
import random
from pathlib import Path
from typing import Awaitable, Callable, Optional

from .config import NewsConfig
from .deduplicator import NewsDeduplicator
from .models import NewsItem
from .drafts import DraftStore, create_draft_from, review_keyboard


log = logging.getLogger("news.publisher")


PreviewSendFn = Callable[[str, dict, Optional[str], Optional[dict]], Awaitable[None]]
# (post_html, inline_keyboard_dict, image_path_or_None, preview_meta_or_None) -> await
# preview_meta: {"draft_id": str, "sector": str, "impact": int, "tone": str, "guard_reasons": list} | None


SendFn = Callable[[str, str, Optional[str]], Awaitable[None]]
# (target_chat_id, html_text, image_path_or_None) -> await


# --- константы текста ---------------------------------------------------------

DISCLAIMER_SHORT = "Не финсовет. Это дневник обучения и AI-разбор."

# Generic-заголовки, которые ЗАПРЕЩЕНО публиковать (P0.3). Сравнение по lower+strip,
# плюс точные подстроки — чтобы поймать «Новость, которая может двигать рынок!» с разной пунктуацией.
GENERIC_TITLE_BLACKLIST = (
    "новость, которая может двигать рынок",
    "новость которая может двигать рынок",
    "новость, за которой стоит следить",
    "новость за которой стоит следить",
    "важная новость",
    "срочно",
    "сегодня в крипте",
    "разбор новости",
    "горячая новость",
)

# Секторные рубрики (Stage 6 §14 + Stage 9). Только хэштеги — заголовок берётся из Claude.
SECTOR_RUBRIC: dict[str, str] = {
    "ai_crypto":                     "#AI_и_крипта",
    "regulation_etf_institutional":  "#новости_без_паники",
    "macro":                         "#новости_без_паники",
    "stablecoins":                   "#новости_без_паники",
    "security_hacks_scams":          "#безопасность_депозита",
    "rwa_tokenization":              "#реальная_крипта",
    "depin_infrastructure":          "#реальная_крипта",
    "political_market_noise":        "#шум_рынка",
    "scam_radar":                    "#скам_радар",
    "memecoins_low_priority":        "#не_будь_хомяком",
}

# Stage 14 — тональности по секторам. Если несколько кандидатов — детерминированный выбор.
SECTOR_TONE_MAP: dict[str, list[str]] = {
    "security_hacks_scams":         ["harsh"],
    "scam_radar":                   ["harsh"],
    "memecoins_low_priority":       ["harsh", "ironic"],
    "macro":                        ["confused"],
    "regulation_etf_institutional": ["confused"],
    "political_market_noise":       ["ironic"],
    "rwa_tokenization":             ["calm"],
    "depin_infrastructure":         ["calm"],
    "stablecoins":                  ["calm"],
    "ai_crypto":                    ["calm"],
}

# Stage 14 — эмодзи-фолбэк по сектору (когда Claude не вернул title_emoji).
SECTOR_EMOJI_FALLBACK: dict[str, str] = {
    "security_hacks_scams":         "🤝",
    "scam_radar":                   "🕵️",
    "regulation_etf_institutional": "🏛️",
    "macro":                        "🌍",
    "ai_crypto":                    "🤖",
    "stablecoins":                  "💵",
    "memecoins_low_priority":       "🎪",
    "rwa_tokenization":             "🏗️",
    "depin_infrastructure":         "🏗️",
    "political_market_noise":       "🧨",
    "other":                        "🗒️",
}

# Stage 12b — fallback image-prompt по сектору. Используется когда Claude не вернул
# image_prompt_hint или вернул слишком короткий. Все промпты — английский, длинные,
# без лиц / текста / логотипов / тикеров. Стиль канала: винтажный крафт, земляная палитра,
# никаких неон-бирюзовых.
SECTOR_IMAGE_HINTS: dict[str, str] = {
    "ai_crypto": (
        "editorial illustration, abstract neural circuits intertwining with subtle "
        "cryptocurrency motifs, vintage craft paper texture, earthy palette of muted "
        "ochre, deep brown and faded teal, soft directional light, no text, no logos, "
        "no human faces, no real ticker symbols"
    ),
    "regulation_etf_institutional": (
        "editorial illustration, classical scales and stacked ledgers next to abstract "
        "blockchain shapes, marble texture in warm sepia tones, vintage craft paper "
        "background, no text, no logos, no real names"
    ),
    "macro": (
        "editorial illustration, abstract global financial currents — ocean tides "
        "merging with grids — earthy palette of warm browns and faded blue-green, "
        "vintage paper grain, no text, no logos, no charts with numbers"
    ),
    "stablecoins": (
        "editorial illustration, anchor and steady pillars half-submerged in calm "
        "water, abstract digital coins floating, warm sepia and muted teal, vintage "
        "craft texture, no text, no logos, no brand names"
    ),
    "security_hacks_scams": (
        "editorial illustration, broken padlock and shadowy hand reaching for a glowing "
        "vault, dramatic muted lighting, earthy ochre + deep navy, vintage paper grain, "
        "no text, no logos, no faces, no brand identifiers"
    ),
    "scam_radar": (
        "editorial illustration, masked figure casting fishing line into a glowing "
        "screen, red flags scattered around, vintage noir tones with faded ochre, "
        "craft paper background, no text, no logos, no real names"
    ),
    "rwa_tokenization": (
        "editorial illustration, abstract real-world assets — bricks, gold ingots, "
        "fields — dissolving into hexagonal blockchain lattice, warm earthy palette, "
        "vintage paper, no text, no logos"
    ),
    "depin_infrastructure": (
        "editorial illustration, decentralized network of antennas and solar panels "
        "across a stylized landscape, warm earthy tones, vintage craft texture, "
        "no text, no logos, no brand names"
    ),
    "defi_restaking": (
        "editorial illustration, layered gears and overlapping rings of energy, "
        "abstract liquidity flows, earthy palette with faded teal accents, "
        "vintage paper grain, no text, no logos"
    ),
    "l2_scaling": (
        "editorial illustration, stacked translucent platforms over a base layer, "
        "abstract blockchain rails ascending, warm sepia and muted teal, "
        "vintage craft texture, no text, no logos"
    ),
    "political_market_noise": (
        "editorial illustration, distorted megaphones echoing across an empty "
        "parliament hall, abstract market grid in background, dramatic muted "
        "ochre + grey palette, vintage paper grain, no text, no logos, no faces, "
        "no flags of real countries"
    ),
    "memecoins_low_priority": (
        "editorial illustration, cartoonish coins floating in a circus tent, "
        "muted ochre and faded red palette, vintage craft texture, "
        "no text, no logos, no real meme characters"
    ),
    "other": (
        "editorial illustration, abstract crypto-market mood, vintage craft paper, "
        "earthy palette of muted ochre and faded teal, soft directional light, "
        "no text, no logos, no faces"
    ),
}


# --- helpers ------------------------------------------------------------------

def _e(s) -> str:
    return html.escape("" if s is None else str(s), quote=False)


def _safe_list(v) -> list[str]:
    """Берём список строк из Claude payload. Допускаем None/list/str."""
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str):
        return [v.strip()] if v.strip() else []
    return []


def news_hash(item: NewsItem) -> str:
    """Стабильный 16-hex хэш новости для кэширования картинок и идемпотентности."""
    raw = f"{item.url}|{item.title}".strip().lower()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def is_generic_title(title: str) -> bool:
    """Проверка на чёрный список generic-заголовков."""
    if not title:
        return True
    t = title.strip().lower().rstrip("!?.,:; ")
    if not t:
        return True
    for bad in GENERIC_TITLE_BLACKLIST:
        if bad in t:
            return True
    return False


def pick_tone(item: "NewsItem", revision_count: int = 0) -> str:
    """Stage 14 — детерминированный выбор тональности по сектору.

    Если сектор имеет одного кандидата — он.
    Если несколько — tones[news_hash(item) % len(tones)].
    При revision_count > 0 — сдвиг для разнообразия при регенерации.
    """
    sector = (item.sector or "other").strip()
    candidates = SECTOR_TONE_MAP.get(sector, ["calm"])
    idx = int(news_hash(item), 16) % len(candidates)
    if revision_count > 0:
        idx = (idx + revision_count) % len(candidates)
    return candidates[idx]


def normalize_payload_v2(payload: dict, item: "NewsItem", revision_count: int = 0) -> dict:
    """Stage 14 — единая точка fallback-логики для v2 payload.

    Возвращает новый dict (вход не модифицируется):
    - title_emoji: если пусто → SECTOR_EMOJI_FALLBACK[sector]
    - tone: если не из enum → pick_tone(item, revision_count)
    - facts: cleanup whitespace и фильтр пустых строк
    - hashtags: применяем merge_hashtags (rubric + assets + claude)
    """
    p = dict(payload)
    sector = (item.sector or "other").strip()

    emoji = str(p.get("title_emoji") or "").strip()
    if not emoji:
        p["title_emoji"] = SECTOR_EMOJI_FALLBACK.get(sector, "🗒️")

    tone = str(p.get("tone") or "").strip().lower()
    if tone not in ("harsh", "confused", "ironic", "calm"):
        p["tone"] = pick_tone(item, revision_count)
    else:
        p["tone"] = tone

    facts_raw = _safe_list(p.get("facts"))
    p["facts"] = [str(f).strip() for f in facts_raw if str(f).strip()]

    p["hashtags"] = merge_hashtags(
        claude_tags=p.get("hashtags") or [],
        sector=sector,
        assets=item.assets or [],
    )

    return p


def inject_mistake_theme(payload: dict, *, counter: int, revision_count: int = 0,
                         themes_path: str = "mistake_themes.json") -> dict:
    """Stage 14 — каждый 5-й пост получает hint с темой ошибки новичка.

    Возвращает (возможно модифицированный) payload. Если инжект не нужен — payload as-is.
    При revision_count > 0 инжект сохраняется (та же тема), чтобы не путать Claude.
    """
    next_post_number = counter + 1
    if next_post_number % 5 != 0:
        return payload

    try:
        themes = json.loads(Path(themes_path).read_text(encoding="utf-8"))
    except Exception:
        return payload

    if not themes:
        return payload

    # Детерминированный выбор темы: хэш от counter, чтобы при регенерации та же тема
    theme_keys = sorted(themes.keys())
    theme_idx = (counter // 5) % len(theme_keys)
    theme = themes[theme_keys[theme_idx]]

    payload["mistake_theme_hint"] = {
        "title": theme.get("title", ""),
        "instruction": (
            "Если уместно к новости — вплети мысль из этой темы в newbie_voice. "
            "Если нерелевантно — игнорируй."
        ),
    }
    return payload


def neutral_sector_header(sector: str) -> str:
    """Stage 12b: нейтральный fallback (используется ТОЛЬКО при render preview когда
    Claude всё-таки вернул дырявый payload, а build_html нужно показать владельцу).

    В канал такие заголовки не уходят — их режет publish_guard.
    Никаких "может двигать рынок" / "стоит следить".
    """
    mapping = {
        "ai_crypto":                     "🤖 <b>AI и крипта</b>",
        "regulation_etf_institutional":  "🏛️ <b>Регулирование и институционалы</b>",
        "macro":                         "🌍 <b>Макро-фон</b>",
        "stablecoins":                   "💵 <b>Стейблкоины</b>",
        "security_hacks_scams":          "🛡️ <b>Безопасность депозита</b>",
        "rwa_tokenization":              "🏗️ <b>Реальная крипта (RWA)</b>",
        "depin_infrastructure":          "🛰️ <b>DePIN-инфраструктура</b>",
        "defi_restaking":                "🔁 <b>DeFi и рестейкинг</b>",
        "l2_scaling":                    "🧱 <b>L2 и масштабирование</b>",
        "political_market_noise":        "🧨 <b>Шум рынка</b>",
        "scam_radar":                    "🕵️ <b>Скам-радар</b>",
        "memecoins_low_priority":        "🎪 <b>Мемкоины</b>",
    }
    return mapping.get(sector, "🗒️ <b>Запись из дневника</b>")


def _system_hashtags_for_sector(sector: str) -> list[str]:
    """Stage 14: только рубрика + активы. Без #новости / #крипта (шум)."""
    rubric = SECTOR_RUBRIC.get(sector, "")
    return [rubric] if rubric else []


def image_prompt_for(item: NewsItem, claude_hint: str = "") -> str:
    """Stage 12b: финальный prompt для OpenAI image-gen.

    Берём claude_hint (если он содержательный, длиннее 16 символов), иначе
    шаблон по сектору. Всегда добавляем no-text/no-logos suffix для безопасности.
    """
    hint = (claude_hint or "").strip()
    sector_template = SECTOR_IMAGE_HINTS.get(item.sector or "other", SECTOR_IMAGE_HINTS["other"])
    base = hint if len(hint) >= 16 else sector_template
    suffix = " no text, no logos, no faces, no real ticker symbols, vintage craft paper texture"
    if "no text" not in base.lower():
        base = base.rstrip(" .,") + "," + suffix
    return base


def merge_hashtags(claude_tags: list[str], sector: str, assets: list[str]) -> list[str]:
    """Stage 14 — мерж хэштегов для v2 поста, max 4.

    Порядок:
    1. Sector rubric (из SECTOR_RUBRIC) — всегда первый, 1 слот
    2. Asset tags (#BTC, #ETH) из assets[:2] — макс 2 слота
    3. Claude thematic tags — добивают до total ≤ 4
    4. Дедупликация регистронезависимая с сохранением порядка
    """
    tags: list[str] = []

    rubric = SECTOR_RUBRIC.get(sector, "")
    if rubric:
        tags.append(rubric)

    for a in (assets or [])[:2]:
        if a in ("BTC", "ETH"):
            tags.append(f"#{a}")

    for t in (claude_tags or []):
        t = str(t).strip()
        if not t:
            continue
        if not t.startswith("#"):
            t = f"#{t}"
        tags.append(t)

    seen: set[str] = set()
    unique: list[str] = []
    for t in tags:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            unique.append(t)

    return unique[:4]


# --- publish-guard ------------------------------------------------------------

REQUIRED_FIELDS = (
    "specific_title",
    "brief_review",
    "key_points",
    "why_it_matters",
    "human_part",
    "mentor_part",
    "beginner_mistake",
    "lesson",
)


def validate_payload_for_publish(payload: dict, item: NewsItem) -> list[str]:
    """Stage 12b publish-guard. Возвращает список причин, по которым публикация
    в канал недопустима. Пустой список = можно публиковать.

    Применяется и при автоматической публикации (run_news_now), и при ручном
    нажатии ✅ владельцем.
    """
    if not isinstance(payload, dict):
        return ["payload не dict (Claude вернул не-JSON)"]

    reasons: list[str] = []

    if not payload.get("should_publish"):
        reasons.append("Claude вернул should_publish=false")

    title = str(payload.get("specific_title") or "").strip()
    if not title:
        reasons.append("specific_title пустой")
    elif is_generic_title(title):
        reasons.append(f"specific_title попадает в blacklist generic-заголовков: «{title[:80]}»")

    for field in ("brief_review", "human_part", "mentor_part", "beginner_mistake", "lesson"):
        if not str(payload.get(field) or "").strip():
            reasons.append(f"{field} пустой")

    if not _safe_list(payload.get("key_points")):
        reasons.append("key_points пустой (нужно 3–5 фактов)")
    if not _safe_list(payload.get("why_it_matters")):
        reasons.append("why_it_matters пустой (нужно 2–4 пункта)")

    if not (item.url or "").strip():
        reasons.append("у новости нет URL источника")

    return reasons


# --- publish-guard v2 (Stage 14) ---------------------------------------------

def validate_payload_v2(payload: dict, item: "NewsItem") -> list[str]:
    """Stage 14 publish-guard для v2 формата. Возвращает список причин блокировки."""
    if not isinstance(payload, dict):
        return ["payload не dict (Claude вернул не-JSON)"]

    reasons: list[str] = []

    if not payload.get("should_publish"):
        reasons.append("Claude вернул should_publish=false")

    title = str(payload.get("specific_title") or "").strip()
    if not title:
        reasons.append("specific_title пустой")
    elif len(title) < 12:
        reasons.append(f"specific_title слишком короткий ({len(title)} < 12 chars)")
    elif len(title) > 80:
        reasons.append(f"specific_title слишком длинный ({len(title)} > 80 chars)")
    elif is_generic_title(title):
        reasons.append(f"specific_title попадает в blacklist generic-заголовков: «{title[:80]}»")

    lead = str(payload.get("lead") or "").strip()
    if not lead:
        reasons.append("lead пустой")
    elif len(lead) < 80:
        reasons.append(f"lead слишком короткий ({len(lead)} < 80 chars)")
    elif len(lead) > 200:
        reasons.append(f"lead слишком длинный ({len(lead)} > 200 chars)")

    facts = _safe_list(payload.get("facts"))
    if len(facts) != 3:
        reasons.append(f"facts должно быть ровно 3, получено {len(facts)}")
    else:
        for i, f in enumerate(facts):
            if len(f) < 30:
                reasons.append(f"fact[{i}] слишком короткий ({len(f)} < 30 chars)")
            elif len(f) > 110:
                reasons.append(f"fact[{i}] слишком длинный ({len(f)} > 110 chars)")

    nv = str(payload.get("newbie_voice") or "").strip()
    if not nv:
        reasons.append("newbie_voice пустой")
    elif len(nv) < 30:
        reasons.append(f"newbie_voice слишком короткий ({len(nv)} < 30 chars)")
    elif len(nv) > 200:
        reasons.append(f"newbie_voice слишком длинный ({len(nv)} > 200 chars)")

    tone = str(payload.get("tone") or "").strip().lower()
    if tone not in ("harsh", "confused", "ironic", "calm"):
        reasons.append(f"tone невалидный: «{tone}» (ожидается harsh/confused/ironic/calm)")

    if not (item.url or "").strip():
        reasons.append("у новости нет URL источника")

    return reasons


# --- HTML render v2 (Stage 14) -----------------------------------------------

def build_html_v2(payload: dict, item: "NewsItem") -> str:
    """Stage 14 — компактный формат поста v2 без заголовков-секций.

    {rubric_hashtag}

    {emoji} <b>{specific_title}</b>

    {lead}

    ➤ {fact_1}
    ➤ {fact_2}
    ➤ {fact_3}

    🐹 {newbie_voice}

    <a href="{url}">{source_name}</a>

    {hashtags}
    """
    sector = item.sector or "other"
    rubric = SECTOR_RUBRIC.get(sector, "")

    emoji = str(payload.get("title_emoji") or "").strip()
    if not emoji:
        emoji = SECTOR_EMOJI_FALLBACK.get(sector, "🗒️")

    specific_title = _e(payload.get("specific_title") or "").strip()
    title_line = f"{emoji} <b>{specific_title}</b>" if specific_title else neutral_sector_header(sector)

    lead = _e(payload.get("lead") or "").strip()

    facts = _safe_list(payload.get("facts"))[:3]

    newbie_voice = _e(payload.get("newbie_voice") or "").strip()

    source_url = _e(item.url)
    source_name = _e(item.source)

    parts: list[str] = []

    if rubric:
        parts.append(rubric)
        parts.append("")

    parts.append(title_line)
    parts.append("")

    if lead:
        parts.append(lead)
        parts.append("")

    for f in facts:
        parts.append(f"➤ {_e(f)}")

    if newbie_voice:
        parts.append("")
        parts.append(f"🐹 {newbie_voice}")

    if source_url:
        parts.append("")
        parts.append(f"<a href=\"{source_url}\">{source_name}</a>")

    tags = merge_hashtags(
        claude_tags=payload.get("hashtags") or [],
        sector=sector,
        assets=item.assets or [],
    )

    if tags:
        parts.append("")
        parts.append(" ".join(tags))

    text = "\n".join(parts).strip()
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text


# --- HTML render (legacy v1, renamed) ----------------------------------------

def build_html_legacy(claude_payload: dict, item: "NewsItem", *, compact: bool = False) -> str:
    """Stage 12b — legacy единый формат поста (v1). Сохранён для обратной совместимости."""
    return build_html(claude_payload, item, compact=compact)


# --- truncate cascade (Stage 14) ----------------------------------------------

def _truncate_post_to_caption_limit(post_html: str, payload: dict, item: "NewsItem") -> str | None:
    """Stage 14 — каскадное урезание поста до ≤ 1024 chars.

    Возвращает урезанный HTML или None если даже после всех шагов > 1024.
    Модифицирует копию payload, не трогает оригинал.
    """
    if len(post_html) <= PHOTO_CAPTION_HARD_LIMIT:
        return post_html

    p = dict(payload)  # работаем на копии

    # Step 1: newbie_voice → 1 фраза (≤ 100 chars)
    nv = str(p.get("newbie_voice") or "")
    if len(_strip_html_tags(nv)) > 100:
        p["newbie_voice"] = _truncate_to_sentence(nv, 100)
        html = build_html_v2(p, item)
        if len(html) <= PHOTO_CAPTION_HARD_LIMIT:
            return html

    # Step 2: удаляем 3-й факт
    facts = list(_safe_list(p.get("facts")))
    if len(facts) >= 3:
        p["facts"] = facts[:2]
        html = build_html_v2(p, item)
        if len(html) <= PHOTO_CAPTION_HARD_LIMIT:
            return html

    # Step 3: lead → 1 фраза (≤ 130 chars)
    lead = str(p.get("lead") or "")
    if len(_strip_html_tags(lead)) > 130:
        p["lead"] = _truncate_to_sentence(lead, 130)
        html = build_html_v2(p, item)
        if len(html) <= PHOTO_CAPTION_HARD_LIMIT:
            return html

    # Step 4: удаляем 2-й факт
    facts = list(_safe_list(p.get("facts")))
    if len(facts) >= 2:
        p["facts"] = facts[:1]
        html = build_html_v2(p, item)
        if len(html) <= PHOTO_CAPTION_HARD_LIMIT:
            return html

    # Step 5: всё ещё > 1024 — отдаём None
    log.warning("truncate cascade exhausted, post still > %d chars", PHOTO_CAPTION_HARD_LIMIT)
    return None


PHOTO_CAPTION_HARD_LIMIT = 1024


# --- HTML render (legacy v1) -------------------------------------------------

def _truncate_to_sentence(text: str, max_chars: int) -> str:
    """Stage 12f compact mode: режет по последней «.», «!» или «?» в пределах max_chars.

    Если предложений нет — режет по последнему пробелу. Не ломает HTML — допускается
    только plain-режим (HTML escape делается выше по стеку).
    """
    if not text or len(text) <= max_chars:
        return text
    s = text[:max_chars]
    for stopper in (". ", "! ", "? "):
        idx = s.rfind(stopper)
        if idx > max_chars * 0.5:
            return s[:idx + 1].strip()
    last_space = s.rfind(" ")
    if last_space > max_chars * 0.5:
        return s[:last_space].rstrip(",;:- ") + "…"
    return s.rstrip(",;:- ") + "…"


def build_html(claude_payload: dict, item: NewsItem, *, compact: bool = False) -> str:
    """Stage 12b — единый формат поста.

    [IMAGE FIRST] (отправляется отдельно как photo+caption)

    <b>{specific_title}</b>

    <b>Коротко:</b>
    {brief_review}

    <b>Главные моменты:</b>
    • ...

    <b>Почему это важно:</b>
    • ...

    🐹 <b>Мысль новичка:</b>
    {human_part}

    🤖 <b>AI-наставник:</b>
    {mentor_part}

    ⚠️ <b>Ошибка новичка:</b>
    {beginner_mistake}

    📌 <b>Вывод:</b>
    {lesson}

    <i>{disclaimer}</i>

    {hashtags}

    Stage 12g: при `compact=True` (используется когда у поста есть image_path
    и мы хотим, чтобы он влез в Telegram photo caption ≤ 1024) автоматически:
    - key_points и why_it_matters ОПУСКАЮТСЯ (дублируют brief)
    - brief_review обрезается до 180 chars (по последней точке)
    - human_part: одно предложение, до 130 chars
    - mentor_part: одно предложение, до 160 chars
    - beginner_mistake: одно предложение, до 100 chars
    - lesson: одно предложение, до 110 chars
    - question и humor_line опускаются
    Цель: одно photo+caption сообщение вместо двух.
    """
    sector = item.sector or "other"
    specific_title = _e(claude_payload.get("specific_title") or "").strip()
    brief_raw = (claude_payload.get("brief_review") or claude_payload.get("short_summary") or "").strip()
    key_points_raw = _safe_list(claude_payload.get("key_points"))
    why_it_matters_raw = _safe_list(claude_payload.get("why_it_matters"))
    human_raw = (claude_payload.get("human_part", "") or "").strip()
    mentor_raw = (claude_payload.get("mentor_part", "") or "").strip()
    mistake_raw = (claude_payload.get("beginner_mistake") or "").strip()
    lesson_raw = (claude_payload.get("lesson") or claude_payload.get("conclusion") or "").strip()
    question_raw = (claude_payload.get("question") or "").strip()

    # Stage 12g compact: режем raw до экранирования, чтобы не ломать HTML-сущности
    if compact:
        brief_raw = _truncate_to_sentence(brief_raw, 180)
        # key_points и why_it_matters опускаем — они и так пересказываются в brief,
        # и именно они раздували caption выше 1024 chars (см. Stage 12g).
        key_points_raw = []
        why_it_matters_raw = []
        human_raw = _truncate_to_sentence(human_raw, 130)
        mentor_raw = _truncate_to_sentence(mentor_raw, 160)
        mistake_raw = _truncate_to_sentence(mistake_raw, 100)
        lesson_raw = _truncate_to_sentence(lesson_raw, 110)
        question_raw = ""   # опускаем

    brief = _e(brief_raw)
    key_points = [s for s in (str(x).strip() for x in key_points_raw) if s]
    why_it_matters = [s for s in (str(x).strip() for x in why_it_matters_raw) if s]
    human = _e(human_raw)
    mentor = _e(mentor_raw)
    mistake = _e(mistake_raw)
    lesson = _e(lesson_raw)
    question = _e(question_raw)

    source_url = _e(item.url)
    source_name = _e(item.source)

    # Заголовок: только specific_title. Если он пустой — нейтральная рубрика
    # (preview-only; в канал такая новость не уйдёт благодаря publish_guard).
    header = f"<b>{specific_title}</b>" if specific_title else neutral_sector_header(sector)

    parts: list[str] = [header, ""]

    if brief:
        parts.append("<b>Коротко:</b>")
        parts.append(brief)
        parts.append("")

    if key_points:
        parts.append("<b>Главные моменты:</b>")
        for kp in key_points[:5]:
            parts.append("• " + _e(kp))
        parts.append("")

    if why_it_matters:
        parts.append("<b>Почему это важно:</b>")
        for wm in why_it_matters[:4]:
            parts.append("• " + _e(wm))
        parts.append("")

    if human:
        parts.append("🐹 <b>Мысль новичка:</b>")
        parts.append(human)
        parts.append("")

    if mentor:
        parts.append("🤖 <b>AI-наставник:</b>")
        parts.append(mentor)
        parts.append("")

    if mistake:
        parts.append("⚠️ <b>Ошибка новичка:</b>")
        parts.append(mistake)
        parts.append("")

    if lesson:
        parts.append("📌 <b>Вывод:</b>")
        parts.append(lesson)
        parts.append("")

    if question:
        parts.append("💬 " + question)
        parts.append("")

    parts.append(f"<i>{_e(DISCLAIMER_SHORT)}</i>")

    if source_url:
        parts.append("")
        parts.append(f"Источник: <a href=\"{source_url}\">{source_name}</a>")

    # --- Хэштеги ---
    raw_tags = claude_payload.get("hashtags") or []
    tags = [t if str(t).startswith("#") else f"#{t}" for t in raw_tags if t]
    system_tags = _system_hashtags_for_sector(sector)
    rubric = SECTOR_RUBRIC.get(sector)
    if rubric and rubric not in system_tags:
        system_tags.append(rubric)
    for a in item.assets[:2]:
        if a in ("BTC", "ETH"):
            system_tags.append(f"#{a}")
    all_tags = list(dict.fromkeys(tags + system_tags))
    if all_tags:
        parts.append("")
        parts.append(" ".join(_e(t) for t in all_tags))

    text = "\n".join(parts).strip()
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text


TG_CAPTION_LIMIT = 1024  # deprecated alias, use PHOTO_CAPTION_HARD_LIMIT


def _strip_html_tags(s: str) -> str:
    """Грубое снятие HTML-тегов для подсчёта plain-длины."""
    import re as _re
    return _re.sub(r"<[^>]+>", "", s or "")


# --- NewsPublisher ------------------------------------------------------------

class NewsPublisher:
    def __init__(
        self,
        config: NewsConfig,
        dedup: NewsDeduplicator,
        *,
        owner_chat_id: str,
        channel_id: str,
        send_fn: SendFn,
        draft_store: Optional[DraftStore] = None,
        preview_send_fn: Optional[PreviewSendFn] = None,
        news_post_counter: int = 0,
    ):
        self.cfg = config
        self.dedup = dedup
        self.owner_chat_id = owner_chat_id
        self.channel_id = channel_id
        self.send = send_fn
        self.draft_store = draft_store
        self.preview_send = preview_send_fn
        self.news_post_counter = news_post_counter

    async def publish(
        self,
        claude_payload: dict,
        item: NewsItem,
        *,
        image_path: Optional[str] = None,
        image_origin: str = "none",
        image_source_url: str = "",
        image_credit: str = "",
        image_prompt: str = "",
        image_model: str = "",
        image_created_at: str = "",
    ) -> str:
        """Возвращает строку-решение:
        'published_channel' | 'preview_sent' | 'sent_owner' | 'skipped' |
        'claude_rejected' | 'guard_blocked' | 'truncation_failed'.
        """
        use_v2 = self.cfg.news_format_version == "v2"
        short_summary = (claude_payload.get("short_summary") or "").strip()

        if not claude_payload.get("should_publish"):
            self.dedup.remember(item, "claude_rejected", short_summary=short_summary)
            return "claude_rejected"

        if item.impact_score < self.cfg.news_min_impact_score:
            self.dedup.remember(item, "skipped", short_summary=short_summary)
            return "skipped"

        if self.dedup.is_duplicate(item):
            self.dedup.remember(item, "skipped", short_summary=short_summary)
            return "skipped"

        # Build post HTML — v2 compact format, v1 может быть compact или full
        if use_v2:
            guard_reasons = validate_payload_v2(claude_payload, item)
            normalized_payload = normalize_payload_v2(claude_payload, item)
            text = build_html_v2(normalized_payload, item)
        else:
            text = build_html_legacy(claude_payload, item, compact=bool(image_path))
            guard_reasons = validate_payload_for_publish(claude_payload, item)
            normalized_payload = claude_payload

        # Stage 14 — truncate cascade для v2
        if use_v2:
            truncated = _truncate_post_to_caption_limit(text, normalized_payload, item)
            if truncated is None:
                # Слишком плотная новость — алерт владельцу, в канал не публикуем
                log.warning(
                    "news truncation failed for %r — post too dense even after cascade",
                    item.title[:80],
                )
                if self.cfg.news_send_to_owner and self.owner_chat_id:
                    try:
                        await self.send(
                            self.owner_chat_id,
                            f"⚠️ <b>Новость слишком плотная для одного поста — посмотри текст</b>\n\n"
                            f"<i>{_e(item.title[:200])}</i>\n\n"
                            f"url: {_e(item.url)}\n"
                            f"sector: {_e(item.sector or '-')} | impact: {int(item.impact_score)}",
                            None,
                        )
                    except Exception:
                        pass
                self.dedup.remember(item, "skipped", short_summary="truncation failed")
                return "skipped"
            text = truncated

        channel_allowed = (
            self.cfg.enable_news
            and self.cfg.news_publish_to_channel
            and not self.cfg.news_dry_run
            and self.channel_id
            and not guard_reasons
        )
        today_count = self.dedup.posted_today(only_channel=True)
        if channel_allowed and today_count >= self.cfg.news_max_posts_per_day:
            channel_allowed = False
            log.info("news day limit reached (%d); routing draft to owner", today_count)

        # Если можно прямо в канал — публикуем сразу.
        if channel_allowed:
            await self.send(self.channel_id, text, image_path)
            self.dedup.remember(item, "published_channel", short_summary=short_summary)
            self.news_post_counter += 1
            return "published_channel"

        # Stage 12g — лимит ревью в день.
        review_quota = getattr(self.cfg, "news_max_reviews_per_day", 0) or 0
        if review_quota > 0:
            today_total = self.dedup.posted_today(only_channel=False)
            if today_total >= review_quota:
                log.info(
                    "news review quota reached (%d/%d) — skipping preview for %r",
                    today_total, review_quota, item.title[:80],
                )
                self.dedup.remember(item, "skipped", short_summary=short_summary)
                return "skipped"

        # Иначе — отдаём на ревью владельцу (Stage 6b).
        if (
            self.draft_store is not None
            and self.preview_send is not None
            and self.cfg.news_send_to_owner
            and self.owner_chat_id
        ):
            draft = create_draft_from(
                claude_payload, item, text,
                image_path=image_path,
                guard_reasons=guard_reasons,
                image_origin=image_origin,
                image_source_url=image_source_url,
                image_credit=image_credit,
                image_prompt=image_prompt,
                image_model=image_model,
                image_created_at=image_created_at,
                schema_version="v2" if use_v2 else "v1",
            )
            self.draft_store.add(draft)
            # Stage 14 — превью без _wrap_preview: 2 мини-сообщения + пост
            # передаются через preview_send с meta
            tone = claude_payload.get("tone", "calm")
            meta = {
                "draft_id": draft.draft_id,
                "sector": item.sector or "other",
                "impact": int(item.impact_score),
                "tone": tone,
                "guard_reasons": guard_reasons,
            }
            await self.preview_send(text, review_keyboard(draft.draft_id), image_path, meta)
            self.dedup.remember(item, "pending_review", short_summary=short_summary)
            return "preview_sent"

        # legacy fallback (без draft_store) — просто DM текстом, без кнопок
        if self.cfg.news_send_to_owner and self.owner_chat_id:
            await self.send(self.owner_chat_id, text, image_path)
            self.dedup.remember(item, "sent_owner", short_summary=short_summary)
            return "sent_owner"

        self.dedup.remember(item, "skipped", short_summary=short_summary)
        return "skipped"
