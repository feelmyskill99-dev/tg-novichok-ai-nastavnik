"""Stage 6 — Crypto News Intelligence.

Собирает новости из RSS + CryptoPanic + CoinMarketCal, скорит по impact/sector,
дедуплицирует, отдаёт Claude для формулировки поста и отправляет в DM/канал.
"""

from .config import NewsConfig
from .models import NewsItem, CATEGORIES, SECTORS
from .collector import NewsCollector
from .scorer import NewsScorer
from .deduplicator import NewsDeduplicator
from .cache import NewsCache
from .analyzer import NewsAnalyzer
from .publisher import (
    NewsPublisher,
    build_html as build_news_html,
    validate_payload_for_publish,
    is_generic_title,
    news_hash,
    image_prompt_for,
    SECTOR_IMAGE_HINTS,
    GENERIC_TITLE_BLACKLIST,
    TG_CAPTION_LIMIT,
)
from .drafts import (
    NewsDraft,
    DraftStore,
    create_draft_from,
    regenerate_payload,
    revise_payload,
    review_keyboard,
    get_recent_published_phrases,
)
from .source_images import NewsSourceImageExtractor
from .orchestrator import run_news_now, run_news_scan, run_news_debug

__all__ = [
    "NewsConfig",
    "NewsItem",
    "CATEGORIES",
    "SECTORS",
    "NewsCollector",
    "NewsScorer",
    "NewsDeduplicator",
    "NewsCache",
    "NewsAnalyzer",
    "NewsPublisher",
    "build_news_html",
    "validate_payload_for_publish",
    "is_generic_title",
    "news_hash",
    "image_prompt_for",
    "SECTOR_IMAGE_HINTS",
    "GENERIC_TITLE_BLACKLIST",
    "TG_CAPTION_LIMIT",
    "NewsDraft",
    "DraftStore",
    "create_draft_from",
    "regenerate_payload",
    "revise_payload",
    "review_keyboard",
    "NewsSourceImageExtractor",
    "run_news_now",
    "run_news_scan",
    "run_news_debug",
]
