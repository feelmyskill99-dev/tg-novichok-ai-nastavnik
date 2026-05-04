"""NewsItem — унифицированное представление новости из любого источника."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


# Категории (тематика по содержанию)
CATEGORIES = [
    "regulation",
    "etf_institutional",
    "exchange_hack_outage",
    "stablecoins",
    "macro",
    "bitcoin",
    "ethereum",
    "altcoins",
    "defi_exploit",
    "token_unlock",
    "lawsuit",
    "liquidations",
    "protocol_upgrade",
    "scam_security",
    "other",
]

# Секторы (приоритет по стратегической значимости, см. спец)
SECTORS = [
    "ai_crypto",
    "stablecoins",
    "rwa_tokenization",
    "regulation_etf_institutional",
    "security_hacks_scams",
    "depin_infrastructure",
    "defi_restaking",
    "l2_scaling",
    "macro",
    # Stage 9: новые рубрики
    "political_market_noise",
    "scam_radar",
    "memecoins_low_priority",
    "other",
]


def _normalize_title(title: str) -> str:
    return " ".join(title.lower().strip().split())


def make_news_id(title: str, source: str) -> str:
    raw = f"{_normalize_title(title)}|{source.lower().strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    published_at: str                   # ISO 8601 UTC
    summary: str = ""
    assets: list[str] = field(default_factory=list)
    category: str = "other"
    sector: str = "other"
    raw_importance: float = 0.0         # от источника (votes/weight/и т.п.), 0..1
    impact_score: float = 0.0           # итоговый 0..100
    id: str = ""
    collected_at: str = ""              # ISO 8601 UTC, выставляется коллектором

    def __post_init__(self) -> None:
        if not self.id:
            self.id = make_news_id(self.title, self.source)
        # нормализуем assets к uppercase-тикерам
        self.assets = [a.upper().strip() for a in self.assets if a]
        if not self.collected_at:
            self.collected_at = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "NewsItem":
        allowed = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in allowed})
