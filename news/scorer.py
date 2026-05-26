"""NewsScorer — rule-based оценка impact (0..100) и определение категории/сектора.

Логика:
1. Детектим category и sector по ключевым словам.
2. Берём sector-base (см. SECTOR_BASE).
3. Если в тексте есть «high-impact» триггеры этого сектора — поднимаем до SECTOR_HIGH_THRESHOLD.
4. Применяем модификаторы:
   +10 — BTC/ETH в assets
   +10 — high-trust source (CoinDesk, Cointelegraph, Reuters, Bloomberg, ...)
   +10 — published_at < 3 часов назад
   +5  — multi-source кластер (≥2 источников по одной теме)
   -20 — price prediction
   -20 — influencer opinion
   -30 — PR release
   -50 — sketchy source (личный блог, твитт, ютуб без редакции)
5. Если NEWS_PRIORITY_AI_CRYPTO=true — ai_crypto получает +5.
6. Memecoin policy: если sector=memecoins_low_priority и NEWS_ALLOW_MEMECOINS=false → impact=0.
7. Зажимаем 0..100.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from dateutil import parser as dtparser

from .config import NewsConfig
from .models import NewsItem


# =============================================================================
# CATEGORIES (тематика)
# =============================================================================

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "etf_institutional":   [r"\betf\b", r"spot etf", r"blackrock", r"fidelity", r"ishares",
                            r"inflow", r"outflow", r"institutional"],
    "regulation":          [r"\bsec\b", r"regulation", r"regulator", r"\bban\b", r"\bmica\b",
                            r"crackdown", r"enforcement"],
    "exchange_hack_outage": [r"\bhack\b", r"exploit", r"drained", r"stolen",
                             r"outage", r"insolven", r"collapse", r"bankrupt"],
    "stablecoins":         [r"stablecoin", r"\busdt\b", r"\busdc\b", r"\bdai\b",
                            r"depeg", r"\bpeg\b"],
    "macro":               [r"\bfed\b", r"\bcpi\b", r"rate hike", r"rate cut",
                            r"interest rate", r"inflation", r"\bfomc\b"],
    "bitcoin":             [r"\bbitcoin\b", r"\bbtc\b", r"halving"],
    "ethereum":            [r"\bethereum\b", r"\beth\b", r"staking"],
    "defi_exploit":        [r"defi.*exploit", r"exploit.*defi", r"flash loan",
                            r"smart contract.*drained"],
    "token_unlock":        [r"\bunlock\b", r"vesting", r"cliff"],
    "lawsuit":             [r"lawsuit", r"\bcourt\b", r"judge", r"ruling", r"subpoena"],
    "liquidations":        [r"liquidat", r"funding stress", r"cascading"],
    "protocol_upgrade":    [r"\bupgrade\b", r"hard fork", r"\bmerge\b"],
    "scam_security":       [r"\bscam\b", r"phishing", r"rug pull", r"deepfake"],
    "altcoins":            [r"altcoin", r"\bxrp\b", r"solana", r"cardano", r"avalanche"],
}


# =============================================================================
# SECTORS (стратегический приоритет)
# =============================================================================

SECTOR_KEYWORDS: dict[str, list[str]] = {
    # Stage 9: scam_radar и political_market_noise проверяются ПЕРВЫМИ — у них более узкие
    # сигналы и они часто пересекаются с другими секторами по ключевым словам.
    "scam_radar": [
        r"\brug pull\b", r"wallet drainer", r"phishing",
        r"fake airdrop", r"fake token launch", r"fake exchange support",
        r"copy.?trading scam", r"vip signal group", r"vip.?signal",
        r"guaranteed (yield|profit|return)", r"ponzi", r"pyramid scheme",
        r"deepfake (crypto|promotion)", r"fake (wallet|exchange) (app|site)",
        r"malicious (browser )?extension", r"seed phrase", r"approval drainer",
        r"3% (a |per )?day", r"\bairdrop scam\b",
    ],
    "political_market_noise": [
        r"\bpresident\b", r"\bsenator\b", r"\bcongress\b", r"\bwhite house\b",
        r"election", r"\btrump\b", r"\bbiden\b", r"sanction(s|ed|ing)",
        r"executive order", r"government shutdown", r"\bgeopolitic",
        r"tariff", r"central bank", r"\becb\b",
        r"sec chair", r"cftc chair", r"treasury secretar",
        # Trump family / business circle (часто двигает крипто-рынок через анонсы)
        r"eric trump", r"donald trump jr", r"trump jr", r"melania trump",
        r"ivanka trump", r"jared kushner", r"world liberty financial",
        r"\bwlfi\b", r"trump media",
        # Middle East / геополитические триггеры с рыночным эффектом
        r"\biran\b", r"\bisrael\b", r"\bhamas\b", r"\bhezbollah\b",
        r"\byemen\b", r"houthi", r"middle east", r"persian gulf",
        r"saudi arabia", r"saudi sovereign", r"\buae\b", r"abu dhabi",
        r"qatar", r"strait of hormuz",
        r"oil (price|spike|surge|shock)", r"crude oil",
        r"missile (strike|attack)", r"airstrike", r"drone strike",
        r"escalation", r"war (in|with)", r"ceasefire",
    ],
    "ai_crypto": [
        r"\bai agent", r"ai agents", r"ai wallet",
        r"decentralized compute", r"\bgpu network", r"\bllm\b",
        r"ai security", r"ai.?token", r"ai x crypto", r"crypto x ai",
        r"autonomous agent", r"on.?chain ai",
    ],
    "stablecoins": [
        r"stablecoin", r"\busdt\b", r"\busdc\b", r"\bdai\b", r"\bfdusd\b", r"\bpyusd\b",
        r"depeg", r"\bpeg\b", r"reserve report", r"large mint", r"large burn",
    ],
    "rwa_tokenization": [
        r"\brwa\b", r"real.world asset", r"tokeniz(ed|ation)",
        r"tokenized treasur", r"tokenized bond", r"tokenized fund",
        r"blackrock", r"franklin templeton",
    ],
    "regulation_etf_institutional": [
        r"\betf\b", r"\bsec\b", r"\bmica\b", r"\bcftc\b",
        r"regulation", r"regulator", r"institutional", r"custody", r"court ruling",
    ],
    "security_hacks_scams": [
        r"\bhack\b", r"exploit", r"drained", r"deepfake",
        r"\bscam\b",
    ],
    "depin_infrastructure": [
        r"\bdepin\b", r"decentralized infrastructure", r"helium", r"akash",
        r"filecoin", r"arweave", r"compute network", r"storage network",
    ],
    "defi_restaking": [
        r"restaking", r"eigenlayer", r"\bdefi\b", r"liquidity pool",
        r"lending protocol", r"\btvl\b",
    ],
    "l2_scaling": [
        r"layer.?2", r"\bl2\b", r"rollup", r"arbitrum", r"optimism",
        r"base network", r"starknet", r"zksync",
    ],
    "macro": [
        r"\bfed\b", r"\bcpi\b", r"\bfomc\b", r"inflation",
        r"rate hike", r"rate cut", r"interest rate",
    ],
    "memecoins_low_priority": [
        r"meme.?coin", r"\bdoge\b", r"\bshib\b", r"\bpepe\b", r"\bwif\b", r"\bbonk\b",
        r"celebrity token",
    ],
}


# Базовый score сектора (см. ТЗ §6 + Stage 9).
SECTOR_BASE: dict[str, int] = {
    "ai_crypto":                     80,
    "stablecoins":                   80,
    "regulation_etf_institutional":  85,
    "security_hacks_scams":          80,
    "rwa_tokenization":              70,
    "depin_infrastructure":          65,
    "defi_restaking":                60,
    "l2_scaling":                    55,
    "macro":                         75,
    # Stage 9
    "political_market_noise":        65,
    "scam_radar":                    80,
    "memecoins_low_priority":        20,
    "other":                         30,
}


# Если в тексте найден один из этих триггеров — base поднимается до THRESHOLD.
SECTOR_HIGH_IMPACT: dict[str, list[str]] = {
    "ai_crypto": [
        r"\bai agent", r"decentralized compute", r"ai wallet",
        r"major ai x crypto", r"ai security incident", r"ai x blockchain",
    ],
    "stablecoins": [
        r"depeg", r"stablecoin regulation", r"issuer reserves",
        r"large mint", r"large burn", r"payment integration", r"systemic risk",
    ],
    "regulation_etf_institutional": [
        r"etf approval", r"etf rejection", r"\bsec\b", r"\bmica\b",
        r"court ruling", r"bank custody", r"institutional adoption", r"spot etf",
    ],
    "security_hacks_scams": [
        r"exploit", r"drained", r"hacked", r"phishing", r"deepfake scam",
        r"affects users",
    ],
    "rwa_tokenization": [
        r"blackrock", r"franklin templeton", r"tokenized treasur",
        r"tokenized fund", r"tokenized bond", r"asset manager",
    ],
    "depin_infrastructure": [
        r"real usage", r"\brevenue\b", r"ai compute", r"storage network",
        r"wireless network", r"major partnership",
    ],
    "defi_restaking": [
        r"large tvl", r"systemic risk", r"security issue",
    ],
    "l2_scaling": [
        r"network upgrade", r"\boutage\b", r"bridge risk",
    ],
    "macro": [
        r"\bcpi\b", r"\bfed\b", r"\bfomc\b", r"rate cut", r"rate hike",
        r"liquidity shock",
    ],
    # Stage 9 + 2026-05-26: расширение под Middle East / Trump family
    "political_market_noise": [
        r"sanction", r"executive order", r"\betf\b", r"\bsec\b", r"\bmica\b",
        r"central bank", r"crypto regulation", r"stablecoin regulation",
        # Геополитика с прямым рыночным эффектом (oil → risk-off → BTC реагирует)
        r"missile (strike|attack)", r"airstrike", r"drone strike",
        r"oil (price|spike|surge|shock)", r"strait of hormuz",
        r"war (in|with) (iran|israel|ukraine|russia)",
        r"ceasefire (deal|agreement|signed)",
        # Trump family — анонсы про крипту (Trump Media, WLFI, мемкойн TRUMP)
        r"trump media", r"world liberty financial", r"\bwlfi\b",
        r"(eric|donald) trump.*(crypto|bitcoin|stablecoin|token)",
    ],
    "scam_radar": [
        r"wallet drainer", r"phishing campaign", r"approval drainer",
        r"\$\d+ ?(m|million|k) drained", r"victims", r"users lost",
        r"deepfake", r"fake (wallet|exchange) (app|site)",
        r"chainalysis report", r"slowmist", r"peckshield", r"certik",
    ],
}

SECTOR_HIGH_THRESHOLD: dict[str, int] = {
    "ai_crypto":                     90,
    "stablecoins":                   85,
    "regulation_etf_institutional":  90,
    "security_hacks_scams":          85,
    "rwa_tokenization":              75,
    "depin_infrastructure":          70,
    "defi_restaking":                65,
    "l2_scaling":                    60,
    "macro":                         85,
    # Stage 9
    "political_market_noise":        85,
    "scam_radar":                    95,
}


# =============================================================================
# SOURCE TRUST
# =============================================================================

HIGH_TRUST_SOURCES = {
    "coindesk", "cointelegraph", "the block", "decrypt",
    "reuters", "bloomberg", "financial times", "wall street journal",
    "wsj", "ft", "ap news", "associated press",
}

# Если source содержит одно из этих — считаем «sketchy» (-50).
SKETCHY_SOURCE_HINTS = (
    "blog", "medium.com", "substack", "youtube", "youtu.be",
    "twitter.com", "x.com", "telegram", "personal",
)


# =============================================================================
# NEGATIVE-MODIFIER KEYWORDS
# =============================================================================

PRICE_PREDICTION_KW = [
    r"price prediction", r"price target", r"will reach \$", r"could hit \$",
    r"to \$\d", r"target.*\$\d", r"by 20\d{2}.*\$",
    r"prediction.*\$", r"forecast.*\$",
]

INFLUENCER_OPINION_KW = [
    r"\binfluencer\b", r"\byoutuber\b", r"crypto personality",
    r"\bsays bitcoin\b", r"\bsays ethereum\b",
    r"according to.*\bcalls\b", r"twitter user",
]

PR_RELEASE_KW = [
    r"press release", r"strategic partnership", r"announces partnership",
    r"sponsored content", r"announces collaboration",
]


# Stage 9: точечные модификаторы для political_market_noise.
POLITICAL_CRYPTO_REG_KW = [
    r"crypto regulation", r"crypto bill", r"\bsec\b", r"\bcftc\b", r"\bmica\b",
    r"\betf\b approval", r"etf rejection", r"stablecoin act",
]
POLITICAL_MACRO_KW = [
    r"interest rate", r"rate (cut|hike)", r"inflation", r"\bcpi\b",
    r"\bdollar\b", r"\bdxy\b", r"\bfomc\b", r"\bfed\b",
]
POLITICAL_EXCHANGE_STABLE_KW = [
    r"exchange ban", r"exchange license", r"stablecoin ban",
    r"\busdt\b", r"\busdc\b", r"binance", r"coinbase", r"kraken",
]
POLITICAL_NO_MARKET_LINK_KW = [
    r"election scandal", r"campaign rally", r"twitter feud",
    r"social media (drama|spat)",
]


# Stage 9: точечные модификаторы для scam_radar.
SCAM_TARGETS_NEWBIES_KW = [
    r"beginner", r"new to crypto", r"new investor", r"target(s|ed) new",
    r"unsuspecting", r"first.?time",
]
SCAM_AI_BOT_YIELD_KW = [
    r"ai (trading )?bot", r"guaranteed (yield|profit|return|income)",
    r"copy.?trading scam", r"vip signal",
    r"3% (a |per )?day", r"\d+% (a |per )?(day|week|month) guaranteed",
]
SCAM_PHISHING_DRAIN_KW = [
    r"wallet drainer", r"approval drainer", r"phishing",
    r"seed phrase", r"fake (wallet|exchange) (app|site|extension)",
    r"malicious extension",
]
SCAM_CONCRETE_EXAMPLE_KW = [
    r"\$\d+(\.\d+)? ?(m|million|k|billion)",
    r"victims? (lost|drained)", r"\d+ users (lost|affected|drained)",
]


# =============================================================================
# SCORER
# =============================================================================

class NewsScorer:
    def __init__(self, config: NewsConfig):
        self.cfg = config

    def score(self, item: NewsItem, *, similar_count: int = 0) -> NewsItem:
        text = f"{item.title} {item.summary}".lower()
        item.category = _match_first(text, CATEGORY_KEYWORDS) or "other"
        item.sector = _match_first(text, SECTOR_KEYWORDS) or "other"

        # 0. memecoin policy: пропускаем сразу
        if item.sector == "memecoins_low_priority" and not self.cfg.news_allow_memecoins:
            item.impact_score = 0.0
            return item

        # 1. base score
        base = SECTOR_BASE.get(item.sector, 30)

        # 2. sector-specific high-impact triggers
        triggers = SECTOR_HIGH_IMPACT.get(item.sector, [])
        if triggers and _has_any(text, triggers):
            threshold = SECTOR_HIGH_THRESHOLD.get(item.sector, base + 5)
            base = max(base, threshold)

        # 3. modifiers
        if any(a in ("BTC", "ETH") for a in item.assets):
            base += 10
        if _is_high_trust(item.source):
            base += 10
        if _is_fresh(item.published_at, hours=3):
            base += 10
        if similar_count >= 2:
            base += 5

        # 4. negatives
        if _has_any(text, PRICE_PREDICTION_KW):
            base -= 20
        if _has_any(text, INFLUENCER_OPINION_KW):
            base -= 20
        if _has_any(text, PR_RELEASE_KW):
            base -= 30
        if _is_sketchy_source(item.source):
            base -= 50

        # 5. AI priority bump
        if item.sector == "ai_crypto" and self.cfg.news_priority_ai_crypto:
            base += 5

        # 6. raw_importance от источника (community votes etc): max +10
        bump = int(min(max(item.raw_importance, 0.0), 1.0) * 10)
        base += bump

        # 7. Stage 9 — sector-specific bonuses
        if item.sector == "political_market_noise":
            base += _political_modifiers(text, item)
        elif item.sector == "scam_radar":
            base += _scam_modifiers(text, item)

        item.impact_score = float(max(0, min(100, base)))
        return item

    def score_batch(self, items: list[NewsItem]) -> list[NewsItem]:
        cluster_size = _cluster_sizes(items)
        return [self.score(it, similar_count=cluster_size.get(it.id, 1)) for it in items]

    def filter_top(
        self,
        items: list[NewsItem],
        *,
        min_score: float,
    ) -> list[NewsItem]:
        scored = self.score_batch(items)
        scored.sort(key=lambda it: it.impact_score, reverse=True)
        return [it for it in scored if it.impact_score >= min_score]


# =============================================================================
# helpers
# =============================================================================

def _match_first(text: str, mapping: dict[str, list[str]]) -> str | None:
    for name, patterns in mapping.items():
        for pat in patterns:
            if re.search(pat, text):
                return name
    return None


def _has_any(text: str, patterns: list[str]) -> bool:
    for pat in patterns:
        if re.search(pat, text):
            return True
    return False


def _is_high_trust(source: str) -> bool:
    if not source:
        return False
    low = source.strip().lower()
    if low in HIGH_TRUST_SOURCES:
        return True
    # допускаем подстроку, но только если source состоит из «нормальных» слов
    for trusted in HIGH_TRUST_SOURCES:
        if trusted in low and not _is_sketchy_source(source):
            return True
    return False


def _is_sketchy_source(source: str) -> bool:
    if not source:
        return True
    low = source.strip().lower()
    return any(hint in low for hint in SKETCHY_SOURCE_HINTS)


def _is_fresh(published_at: str, *, hours: int) -> bool:
    if not published_at:
        return False
    try:
        dt = dtparser.parse(published_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt >= datetime.now(tz=timezone.utc) - timedelta(hours=hours)
    except Exception:
        return False


def _political_modifiers(text: str, item: NewsItem) -> int:
    """Sector-aware bonusy для political_market_noise (см. Stage 9 §13)."""
    delta = 0
    if _has_any(text, POLITICAL_CRYPTO_REG_KW):
        delta += 20
    if _has_any(text, POLITICAL_MACRO_KW):
        delta += 15
    if _has_any(text, POLITICAL_EXCHANGE_STABLE_KW):
        delta += 15
    if any(a in ("BTC", "ETH") for a in item.assets):
        delta += 10
    # если совсем нет связи с рынком — большая отрицательная компенсация
    market_link = (
        _has_any(text, POLITICAL_CRYPTO_REG_KW)
        or _has_any(text, POLITICAL_MACRO_KW)
        or _has_any(text, POLITICAL_EXCHANGE_STABLE_KW)
        or any(a for a in item.assets)
    )
    if not market_link:
        delta -= 30
    if _has_any(text, POLITICAL_NO_MARKET_LINK_KW) and not market_link:
        delta -= 30
    return delta


def _scam_modifiers(text: str, item: NewsItem) -> int:
    """Sector-aware bonusy для scam_radar (см. Stage 9 §16)."""
    delta = 0
    if _has_any(text, SCAM_TARGETS_NEWBIES_KW):
        delta += 20
    if _has_any(text, SCAM_AI_BOT_YIELD_KW):
        delta += 20
    if _has_any(text, SCAM_PHISHING_DRAIN_KW):
        delta += 15
    if _has_any(text, SCAM_CONCRETE_EXAMPLE_KW):
        delta += 15
    return delta


def _cluster_sizes(items: list[NewsItem]) -> dict[str, int]:
    """Группируем по первым 5 словам нормализованного title.

    Возвращаем dict[item.id → cluster size]. Используется для +5 multi-source бонуса.
    """
    clusters: dict[str, list[str]] = {}
    keys: dict[str, str] = {}
    for it in items:
        words = re.sub(r"[^a-z0-9 ]+", " ", it.title.lower()).split()
        key = " ".join(words[:5]) if len(words) >= 3 else it.id
        keys[it.id] = key
        clusters.setdefault(key, []).append(it.id)
    return {iid: len(clusters[k]) for iid, k in keys.items()}
