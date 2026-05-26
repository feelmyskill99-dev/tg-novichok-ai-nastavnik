"""Content mix — чистая функция без I/O (этап 2.2).

Bot.py и admin_panel.py раньше дублировали логику. Теперь оба используют
`compute_mix(log_list, now=...)` отсюда.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

CONTENT_MIX_TARGET: dict[str, float] = {
    "market_chart": 0.40,
    "education":    0.20,
    "news":         0.15,
    "author_note":  0.15,
    "trade_diary":  0.10,
}
CONTENT_MIX_WINDOW_DAYS = 7
CONTENT_MIX_LOG_CAP = 500
CONTENT_MIX_OVERREP_DELTA = 0.10
CONTENT_MIX_UNDERREP_DELTA = 0.07
CONTENT_MIX_CHANNEL_MODE_MIN = 3
CONTENT_MIX_LOW_DATA_THRESHOLD = 3
CONTENT_MIX_FALLBACK_RECOMMEND = "education"

# raw post_type → canonical category. Свёрнутые синонимы из всех модулей.
CATEGORY_MAP: dict[str, str] = {
    "market":           "market_chart",
    "btc_overview":     "market_chart",
    "chart_analysis":   "market_chart",
    "flash":            "market_chart",

    "education":            "education",
    "fallback_education":   "education",
    "glossary":             "education",
    "term_without_pain":    "education",
    "anti_signal":          "education",
    "risk_management":      "education",

    "news":                       "news",
    "news_analysis":              "news",
    "ai_crypto":                  "news",
    "political_market_noise":     "news",
    "scam_radar":                 "news",
    "security_news":              "news",
    "security_hacks_scams":       "news",
    "stablecoins":                "news",
    "rwa":                        "news",
    "rwa_tokenization":           "news",
    "depin":                      "news",
    "depin_infrastructure":       "news",
    "regulation_etf_institutional": "news",
    "macro":                      "news",
    "memecoins_low_priority":     "news",

    "author_note":      "author_note",
    "personal_note":    "author_note",
    "what_i_learned":   "author_note",
    "hamster_dialogue": "author_note",

    "trade":                "trade_diary",
    "paper_trade":          "trade_diary",
    "trade_review":         "trade_diary",
    "closed_trade":         "trade_diary",
    "weekly_trade_report":  "trade_diary",
}


def category_for(post_type: str) -> str:
    return CATEGORY_MAP.get((post_type or "").lower().strip(), "other")


def compute_mix(log_list: list[dict], *, now: Optional[datetime] = None) -> dict:
    """Pure function: даёт срез content-mix за окно CONTENT_MIX_WINDOW_DAYS.

    Args:
        log_list: события вида {timestamp, post_type, category, published_to, ...}
        now: точка отсчёта (для тестов). По умолчанию — datetime.now(utc).

    Returns:
        dict с ключами: mode, total_posts, counts, other_count, shares, target,
        overrepresented, underrepresented, recommended, reason.
    """
    now = now or datetime.now(tz=timezone.utc)
    cutoff = now - timedelta(days=CONTENT_MIX_WINDOW_DAYS)

    fresh: list[dict] = []
    for ev in log_list or []:
        try:
            ts = datetime.fromisoformat(ev.get("timestamp") or "")
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= cutoff:
                fresh.append(ev)
        except Exception:
            continue

    channel_only = [e for e in fresh if e.get("published_to") == "channel"]
    if len(channel_only) >= CONTENT_MIX_CHANNEL_MODE_MIN:
        events = channel_only
        mode = "channel"
    else:
        events = fresh
        mode = "all"

    counts: dict[str, int] = {c: 0 for c in CONTENT_MIX_TARGET}
    other_count = 0
    for e in events:
        cat = e.get("category") or "other"
        if cat in counts:
            counts[cat] += 1
        else:
            other_count += 1
    target_total = sum(counts.values())
    total = target_total + other_count

    shares = {
        c: (counts[c] / target_total) if target_total > 0 else 0.0
        for c in counts
    }

    over = [c for c in CONTENT_MIX_TARGET
            if shares[c] > CONTENT_MIX_TARGET[c] + CONTENT_MIX_OVERREP_DELTA]
    under = [c for c in CONTENT_MIX_TARGET
             if shares[c] < CONTENT_MIX_TARGET[c] - CONTENT_MIX_UNDERREP_DELTA]

    if total < CONTENT_MIX_LOW_DATA_THRESHOLD:
        recommended = CONTENT_MIX_FALLBACK_RECOMMEND
        reason = (f"мало данных ({total} событий за {CONTENT_MIX_WINDOW_DAYS}д) "
                  f"— fallback на «{CONTENT_MIX_FALLBACK_RECOMMEND}», "
                  f"чтобы канал не был сухим")
    elif under:
        worst = sorted(under, key=lambda c: shares[c] - CONTENT_MIX_TARGET[c])[0]
        recommended = worst
        deficit = (CONTENT_MIX_TARGET[worst] - shares[worst]) * 100
        reason = (f"{worst} = {round(shares[worst]*100)}% "
                  f"(цель {round(CONTENT_MIX_TARGET[worst]*100)}%), "
                  f"дефицит {round(deficit)} п.п.")
    elif over:
        candidates = [c for c in CONTENT_MIX_TARGET if c not in over]
        if candidates:
            recommended = min(candidates, key=lambda c: shares[c] - CONTENT_MIX_TARGET[c])
        else:
            recommended = CONTENT_MIX_FALLBACK_RECOMMEND
        reason = ("есть перекос (" + ", ".join(over) + ") — рекомендуем "
                  f"не повторять, следующий лучше «{recommended}»")
    else:
        recommended = "market_chart"
        reason = "все категории в пределах коридора — можно обычный рыночный пост"

    return {
        "mode": mode,
        "total_posts": total,
        "counts": counts,
        "other_count": other_count,
        "shares": shares,
        "target": dict(CONTENT_MIX_TARGET),
        "overrepresented": over,
        "underrepresented": under,
        "recommended": recommended,
        "reason": reason,
    }
