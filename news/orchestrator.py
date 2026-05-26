"""Оркестратор новостной подсистемы для bot.py.

Три входа:
    run_news_now   — собрать, проскорить, дать Claude, опубликовать (или в DM)
    run_news_scan  — собрать, проскорить, вывести топ-5 в консоль (без Claude и без публикации)
    run_news_debug — то же что scan, но с детализацией по каждой новости (sector,
                     impact_score, decision, reason)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
from typing import Awaitable, Callable, Optional

from anthropic import Anthropic

from .analyzer import NewsAnalyzer
from .cache import NewsCache
from .collector import NewsCollector
from .config import NewsConfig
from .deduplicator import NewsDeduplicator
from .drafts import DraftStore
from .models import NewsItem
from .publisher import NewsPublisher, PreviewSendFn, SendFn
from .scorer import NewsScorer


log = logging.getLogger("news.orchestrator")


# Stage 12b — провайдер картинок. bot.py подставляет async-callable, который зовёт
# OpenAI generate_image() и кэширует по news_hash. Если None — orchestrator просто
# не генерит и публикует текст без image_path (старое поведение).
ImageProvider = Callable[[NewsItem, dict], Awaitable[Optional[str]]]


async def run_news_now(
    *,
    config: NewsConfig,
    cache_path: Path,
    history_path: Path,
    owner_chat_id: str,
    channel_id: str,
    send_fn: SendFn,
    claude: Anthropic,
    claude_model: str,
    market_snapshot: Optional[dict] = None,
    drafts_path: Optional[Path] = None,
    preview_send_fn: Optional[PreviewSendFn] = None,
    image_provider: Optional[ImageProvider] = None,
    counter_get: Optional[Callable[[], int]] = None,
    counter_inc: Optional[Callable[[], int]] = None,
) -> dict:
    """Полный пайплайн: collect → score → dedup → Claude → publish.

    market_snapshot — опциональный dict с BTC/ETH price/change/funding/OI.
    Передаётся в Claude как контекст, но без утверждения причинно-следственной связи.

    Возвращает короткий отчёт dict (для логов / отладки).
    """
    if not config.enable_news:
        log.info("ENABLE_NEWS=false, пропускаем")
        return {"ok": False, "reason": "news disabled"}

    collector = NewsCollector(config)
    scorer = NewsScorer(config)
    dedup = NewsDeduplicator(history_path)
    cache = NewsCache(cache_path)

    items = await collector.collect()
    if not items:
        log.info("новостей нет (в окне %dч)", config.news_lookback_hours)
        cache.save([])
        return {"ok": False, "reason": "no news in lookback window"}

    scored = scorer.score_batch(items)
    cache.save(scored)

    # отфильтровать: impact выше порога + не дубликат
    candidates: list[NewsItem] = []
    for it in scored:
        if it.impact_score < config.news_min_impact_score:
            continue
        if dedup.is_duplicate(it):
            continue
        candidates.append(it)

    if not candidates:
        return {
            "ok": False,
            "reason": "нет новостей выше порога или все дубликаты",
            "total_collected": len(scored),
        }

    # даём Claude топ-5 (он сам выберет одну)
    candidates.sort(key=lambda it: it.impact_score, reverse=True)
    top = candidates[:5]

    analyzer = NewsAnalyzer(config, claude, claude_model)
    # Stage 12f anti-repetition: подсовываем фразы из недавних published-постов,
    # чтобы Claude не повторял штампы.
    previous_phrases: list[str] = []
    if drafts_path:
        try:
            from .drafts import get_recent_published_phrases
            previous_phrases = get_recent_published_phrases(DraftStore(drafts_path), limit=8)
        except Exception as e:
            log.warning("get_recent_published_phrases failed: %s", e)
    # Stage 14 — mistake_theme inject каждый 5-й опубликованный пост.
    mistake_hint: Optional[dict] = None
    if counter_get is not None:
        try:
            current_counter = int(counter_get())
        except Exception:
            current_counter = 0
        next_post_number = current_counter + 1
        if next_post_number % 5 == 0:
            try:
                from .publisher import inject_mistake_theme
                # inject_mistake_theme модифицирует payload; здесь нам нужен только hint.
                # Соберём через временный dict.
                tmp = {}
                inject_mistake_theme(tmp, counter=current_counter)
                mistake_hint = tmp.get("mistake_theme_hint")
            except Exception as e:
                log.warning("mistake_theme inject failed: %s", e)
    payload = analyzer.analyze(
        top,
        market_snapshot=market_snapshot,
        previous_phrases_to_avoid=previous_phrases,
        mistake_theme_hint=mistake_hint,
    )

    if not payload.get("should_publish"):
        reason = payload.get("reason", "claude rejected")
        log.info("claude decided not to publish: %s", reason)
        dedup.remember(top[0], "claude_rejected", short_summary=payload.get("short_summary", ""))
        return {"ok": False, "reason": f"claude: {reason}", "top_candidate": top[0].title}

    # main_news по url, иначе первый топ
    chosen_url = (payload.get("main_news") or {}).get("url") or ""
    chosen = next((it for it in top if it.url == chosen_url), top[0])

    # Stage 12e — image strategy. По умолчанию NEWS_IMAGE_MODE=source_preview:
    # тащим og:image из источника. AI-картинку генерим ТОЛЬКО если allow_auto_generated_images=true.
    image_path: Optional[str] = None
    image_origin = "none"
    image_source_url = ""
    image_credit = ""
    image_prompt = ""
    image_model = ""
    image_created_at = ""

    mode = (config.news_image_mode or "source_preview").lower()

    # 1) source preview — приоритет
    if (
        mode in ("source_preview", "generated_on_approval")
        and config.news_use_source_preview
    ):
        try:
            from .source_images import NewsSourceImageExtractor
            extractor = NewsSourceImageExtractor(Path(config.news_source_image_save_dir))
            local_path, src_url = extractor.get_source_image(chosen)
        except Exception as e:
            log.warning("source-image extractor crashed: %s", e)
            local_path, src_url = (None, None)
        if local_path:
            image_path = local_path
            image_origin = "source_preview"
            image_source_url = src_url or ""
            image_credit = chosen.source or ""
            image_created_at = _now_iso()
            log.info("news image: source_preview взято из %s", src_url or "rss")

    # 2) AI-fallback или auto-AI — только при явном разрешении
    auto_ai_allowed = (
        config.news_allow_auto_generated_images
        and image_provider is not None
        and chosen.impact_score >= config.news_image_min_impact_score
    )
    auto_ai_should_run = False
    if mode == "generated_auto" and auto_ai_allowed:
        auto_ai_should_run = True
    elif (
        not image_path
        and mode == "source_preview"
        and config.news_image_fallback_to_generated
        and auto_ai_allowed
    ):
        auto_ai_should_run = True

    if auto_ai_should_run:
        try:
            ai_path = await image_provider(chosen, payload)
            if ai_path:
                image_path = ai_path
                image_origin = "generated_ai"
                image_source_url = ""
                image_credit = chosen.source or ""
                image_prompt = (payload.get("image_prompt_hint") or "")[:500]
                image_model = "openai-image"
                image_created_at = _now_iso()
                log.info("news image: AI-fallback сработал (impact=%s)", chosen.impact_score)
            else:
                log.info("news image: AI-fallback вернул None (impact=%s)", chosen.impact_score)
        except Exception as e:
            log.exception("news image_provider crashed: %s", e)

    draft_store = DraftStore(drafts_path) if drafts_path else None
    publisher = NewsPublisher(
        config, dedup,
        owner_chat_id=owner_chat_id,
        channel_id=channel_id,
        send_fn=send_fn,
        draft_store=draft_store,
        preview_send_fn=preview_send_fn,
        counter_get=counter_get,
        counter_inc=counter_inc,
    )
    decision = await publisher.publish(
        payload, chosen,
        image_path=image_path,
        image_origin=image_origin,
        image_source_url=image_source_url,
        image_credit=image_credit,
        image_prompt=image_prompt,
        image_model=image_model,
        image_created_at=image_created_at,
    )

    return {
        "ok": True,
        "decision": decision,
        "chosen_title": chosen.title,
        "chosen_source": chosen.source,
        "impact_score": chosen.impact_score,
        "sector": chosen.sector,
        "category": chosen.category,
        "image_path": image_path or "",
        "image_origin": image_origin,
    }


async def run_news_scan(
    *,
    config: NewsConfig,
    cache_path: Path,
) -> list[dict]:
    """Быстрый скан без Claude и без публикации. Печатает топ-5 в консоль."""
    collector = NewsCollector(config)
    scorer = NewsScorer(config)
    cache = NewsCache(cache_path)

    items = await collector.collect()
    scored = scorer.score_batch(items)
    cache.save(scored)

    scored.sort(key=lambda it: it.impact_score, reverse=True)
    top = scored[:5]

    compact = [
        {
            "impact": it.impact_score,
            "sector": it.sector,
            "category": it.category,
            "source": it.source,
            "title": it.title,
            "url": it.url,
            "published_at": it.published_at,
        }
        for it in top
    ]
    print(json.dumps(compact, ensure_ascii=False, indent=2))
    return compact


async def run_news_debug(
    *,
    config: NewsConfig,
    cache_path: Path,
    history_path: Path,
) -> list[dict]:
    """Подробный отладочный скан: показывает по каждой новости — sector, impact_score,
    решение (publish/skip/dup) и причину. Без Claude и без публикации.

    Полезно при настройке скоринга и при добавлении новых ключевых слов.
    """
    collector = NewsCollector(config)
    scorer = NewsScorer(config)
    dedup = NewsDeduplicator(history_path)
    cache = NewsCache(cache_path)

    items = await collector.collect()
    scored = scorer.score_batch(items)
    cache.save(scored)

    scored.sort(key=lambda it: it.impact_score, reverse=True)

    from .publisher import (
        SECTOR_IMAGE_HINTS, neutral_sector_header, news_hash, is_generic_title,
    )

    rows: list[dict] = []
    for it in scored:
        decision = "skip"
        reason = ""
        if it.sector == "memecoins_low_priority" and not config.news_allow_memecoins:
            decision = "skip"
            reason = "memecoin filtered (NEWS_ALLOW_MEMECOINS=false)"
        elif it.impact_score < config.news_min_impact_score:
            decision = "skip"
            reason = f"impact {it.impact_score} < {config.news_min_impact_score}"
        elif dedup.is_duplicate(it):
            decision = "skip"
            reason = "duplicate (in history within 48h)"
        else:
            decision = "publish_candidate"
            reason = "passes all filters → would go to Claude"

        # Stage 12b — расширенная диагностика
        would_image = (
            config.news_auto_image
            and it.impact_score >= config.news_image_min_impact_score
            and decision == "publish_candidate"
        )
        sector_template = SECTOR_IMAGE_HINTS.get(it.sector or "other", "")
        sector_header = neutral_sector_header(it.sector or "other")
        rows.append({
            "impact": it.impact_score,
            "sector": it.sector,
            "category": it.category,
            "source": it.source,
            "title": it.title,
            "url": it.url,
            "published_at": it.published_at,
            "decision": decision,
            "reason": reason,
            "news_hash": news_hash(it),
            "would_generate_image": would_image,
            "sector_image_template_chars": len(sector_template),
            "neutral_sector_header": sector_header,
            "title_is_generic": is_generic_title(it.title),
        })

    # человеко-читаемый вывод
    print(f"--- news debug: {len(rows)} items ---")
    print(
        f"thresholds: NEWS_MIN_IMPACT_SCORE={config.news_min_impact_score}, "
        f"NEWS_IMAGE_MIN_IMPACT_SCORE={config.news_image_min_impact_score}, "
        f"NEWS_AUTO_IMAGE={config.news_auto_image}"
    )
    for r in rows[:25]:
        img_flag = "[IMG]" if r["would_generate_image"] else "     "
        gen_flag = "[GEN]" if r["title_is_generic"] else "     "
        print(
            f"[{r['impact']:>3.0f}] {img_flag} {gen_flag} {r['decision']:<18} | "
            f"hash={r['news_hash']} | "
            f"{r['sector']:<28} | {r['source']:<18} | {r['title'][:70]}"
        )
        if r["decision"] == "skip":
            print(f"        reason: {r['reason']}")
        if r["title_is_generic"]:
            print(f"        [WARN] title в blacklist generic-заголовков")
    return rows
