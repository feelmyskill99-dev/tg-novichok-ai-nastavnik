"""NewsConfig — все .env-параметры новостной подсистемы в одном dataclass."""

from __future__ import annotations

import os
from dataclasses import dataclass

from core.env_helpers import env_bool, env_int, env_str


# Этап 2.3: алиасы; реальная логика в core/env_helpers.
def _bool(name: str, default: bool) -> bool:
    return env_bool(name, default=default)


def _int(name: str, default: int) -> int:
    return env_int(name, default=default)


def _str(name: str, default: str) -> str:
    return env_str(name, default=default)


@dataclass(frozen=True)
class NewsConfig:
    enable_news: bool = True
    news_dry_run: bool = True
    news_min_impact_score: int = 75
    news_max_posts_per_day: int = 1
    news_max_reviews_per_day: int = 2
    news_lookback_hours: int = 12
    news_scan_interval_minutes: int = 60

    cryptopanic_api_key: str = ""
    coinmarketcal_api_key: str = ""

    news_publish_to_channel: bool = False
    news_send_to_owner: bool = True

    # Авто-публикация новостей с высоким impact (минуя ручное ревью).
    # 0 = выключено. >0 = новости с item.impact_score >= порога идут сразу в канал
    # (с сохранением остальных предохранителей: news_max_posts_per_day,
    # news_dry_run, enable_news, dedup, guard).
    news_auto_publish_min_impact: int = 0

    news_humor_level: str = "light"       # off | light | medium
    news_sarcasm_level: str = "light"     # off | light | medium

    news_priority_ai_crypto: bool = True
    news_allow_memecoins: bool = False

    # Stage 12b — auto image generation (deprecated в пользу 12e, оставлен для backward-compat)
    news_auto_image: bool = True                # глобальный outlet (legacy — игнорируется при image_mode != generated_auto)
    news_image_min_impact_score: int = 80       # auto-AI порог (используется только при NEWS_ALLOW_AUTO_GENERATED_IMAGES=true)

    # Stage 12e — source image strategy.
    # По умолчанию: тащим og:image / twitter:image из источника, AI-картинку
    # генерируем ТОЛЬКО по нажатию кнопки 🖼 владельцем. OpenAI Image API
    # никогда не вызывается автоматически, если allow_auto_generated_images=false.
    news_image_mode: str = "source_preview"     # source_preview | generated_on_approval | generated_auto | none
    news_use_source_preview: bool = True
    news_generate_image_only_on_approval: bool = True
    news_allow_auto_generated_images: bool = False
    news_image_fallback_to_generated: bool = False
    news_source_image_save_dir: str = "outputs/news_source_images"
    news_generated_image_save_dir: str = "outputs/news_images"

    # Stage 14 — news format version. "v2" = compact voiced posts, "v1" = legacy 9-section.
    news_format_version: str = "v2"

    @classmethod
    def from_env(cls) -> "NewsConfig":
        return cls(
            enable_news=_bool("ENABLE_NEWS", True),
            news_dry_run=_bool("NEWS_DRY_RUN", True),
            news_min_impact_score=_int("NEWS_MIN_IMPACT_SCORE", 75),
            news_max_posts_per_day=_int("NEWS_MAX_POSTS_PER_DAY", 1),
            news_max_reviews_per_day=_int("NEWS_MAX_REVIEWS_PER_DAY", 2),
            news_lookback_hours=_int("NEWS_LOOKBACK_HOURS", 12),
            news_scan_interval_minutes=_int("NEWS_SCAN_INTERVAL_MINUTES", 60),

            cryptopanic_api_key=_str("CRYPTOPANIC_API_KEY", ""),
            coinmarketcal_api_key=_str("COINMARKETCAL_API_KEY", ""),

            news_publish_to_channel=_bool("NEWS_PUBLISH_TO_CHANNEL", False),
            news_send_to_owner=_bool("NEWS_SEND_TO_OWNER", True),
            news_auto_publish_min_impact=_int("NEWS_AUTO_PUBLISH_MIN_IMPACT", 0),

            news_humor_level=_str("NEWS_HUMOR_LEVEL", "light").lower(),
            news_sarcasm_level=_str("NEWS_SARCASM_LEVEL", "light").lower(),

            news_priority_ai_crypto=_bool("NEWS_PRIORITY_AI_CRYPTO", True),
            news_allow_memecoins=_bool("NEWS_ALLOW_MEMECOINS", False),

            news_auto_image=_bool("NEWS_AUTO_IMAGE", True),
            news_image_min_impact_score=_int("NEWS_IMAGE_MIN_IMPACT_SCORE", 80),

            news_image_mode=_str("NEWS_IMAGE_MODE", "source_preview").lower(),
            news_use_source_preview=_bool("NEWS_USE_SOURCE_PREVIEW", True),
            news_generate_image_only_on_approval=_bool("NEWS_GENERATE_IMAGE_ONLY_ON_APPROVAL", True),
            news_allow_auto_generated_images=_bool("NEWS_ALLOW_AUTO_GENERATED_IMAGES", False),
            news_image_fallback_to_generated=_bool("NEWS_IMAGE_FALLBACK_TO_GENERATED", False),
            news_source_image_save_dir=_str("NEWS_SOURCE_IMAGE_SAVE_DIR", "outputs/news_source_images"),
            news_generated_image_save_dir=_str("NEWS_GENERATED_IMAGE_SAVE_DIR", "outputs/news_images"),

            news_format_version=_str("NEWS_FORMAT_VERSION", "v2").lower(),
        )
