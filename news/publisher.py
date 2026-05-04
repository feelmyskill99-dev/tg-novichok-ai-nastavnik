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
import logging
from typing import Awaitable, Callable, Optional

from .config import NewsConfig
from .deduplicator import NewsDeduplicator
from .models import NewsItem
from .drafts import DraftStore, create_draft_from, review_keyboard


log = logging.getLogger("news.publisher")


PreviewSendFn = Callable[[str, dict, Optional[str]], Awaitable[None]]
# (html_text, inline_keyboard_dict, image_path_or_None) -> await


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
    """Системные хэштеги, которые ставим всегда (плюс секторная рубрика)."""
    if sector == "political_market_noise":
        return ["#шум_рынка", "#новости_без_паники", "#крипта"]
    if sector == "scam_radar":
        return ["#скам_радар", "#безопасность_депозита", "#не_будь_хомяком"]
    return ["#новости", "#крипта"]


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


# --- HTML render --------------------------------------------------------------

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


# --- short caption (для photo с длинным текстом) -----------------------------

TG_CAPTION_LIMIT = 1024


def short_caption(claude_payload: dict, item: NewsItem) -> str:
    """Короткий caption для photo, когда полный текст не влезает в 1024 chars.

    Включает specific_title + 1-2 ключевых факта + хвостик-хэштеги.
    """
    title = _e(claude_payload.get("specific_title") or "").strip()
    if not title:
        title = neutral_sector_header(item.sector or "other")
    else:
        title = f"<b>{title}</b>"
    brief = _e(claude_payload.get("brief_review") or claude_payload.get("short_summary") or "").strip()
    parts = [title]
    if brief:
        parts.append("")
        parts.append(brief[:300])
    parts.append("")
    parts.append("<i>↓ полный разбор ниже</i>")
    out = "\n".join(parts).strip()
    if len(out) > TG_CAPTION_LIMIT - 40:
        out = out[:TG_CAPTION_LIMIT - 40].rstrip() + "…"
    return out


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
    ):
        self.cfg = config
        self.dedup = dedup
        self.owner_chat_id = owner_chat_id
        self.channel_id = channel_id
        self.send = send_fn
        self.draft_store = draft_store
        self.preview_send = preview_send_fn

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
        'claude_rejected' | 'guard_blocked'.
        """
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

        # Stage 12f — если есть картинка, рендерим compact, чтобы вместе с фото
        # умещалось в Telegram caption ≤ 1024 chars (одно сообщение в канале).
        text = build_html(claude_payload, item, compact=bool(image_path))

        # Stage 12b publish-guard. Применяем до решения о канале — если payload
        # дырявый (нет specific_title / generic / нет фактов), уходит на ревью
        # владельцу с алертом, никогда не в канал.
        guard_reasons = validate_payload_for_publish(claude_payload, item)

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
            return "published_channel"

        # Stage 12g — лимит ревью в день. Считаем все non-skipped события за сегодня
        # (pending_review, sent_owner, published_channel) — если уже больше квоты,
        # не шлём владельцу новые превью, чтобы не заваливать DM.
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
            )
            self.draft_store.add(draft)
            preview = self._wrap_preview(text, draft.draft_id, item, guard_reasons)
            await self.preview_send(preview, review_keyboard(draft.draft_id), image_path)
            self.dedup.remember(item, "pending_review", short_summary=short_summary)
            return "preview_sent"

        # legacy fallback (без draft_store) — просто DM текстом, без кнопок
        if self.cfg.news_send_to_owner and self.owner_chat_id:
            await self.send(self.owner_chat_id, text, image_path)
            self.dedup.remember(item, "sent_owner", short_summary=short_summary)
            return "sent_owner"

        self.dedup.remember(item, "skipped", short_summary=short_summary)
        return "skipped"

    @staticmethod
    def _wrap_preview(post_text: str, draft_id: str, item: NewsItem, guard_reasons: list[str]) -> str:
        sector = html.escape(item.sector or "-", quote=False)
        impact = int(item.impact_score)
        head_lines = [
            "🧪 <b>Превью новостного поста — нужен ревью</b>",
            f"draft_id: <code>{html.escape(draft_id, quote=False)}</code> | "
            f"sector: {sector} | impact: {impact}",
        ]
        if guard_reasons:
            head_lines.append("")
            head_lines.append("🚫 <b>Publish-guard заблокировал автопубликацию:</b>")
            for r in guard_reasons[:6]:
                head_lines.append(f"• {html.escape(r, quote=False)}")
            head_lines.append("Поправь правкой ✏️ или перегенерь 🔁 перед ✅.")
        head_lines.append("──────────────")
        return "\n".join(head_lines) + "\n\n" + post_text
