"""NewsCache — news_cache.json: сырые собранные новости (не только отобранные).

Помогает отлаживать скоринг и анализировать «почему не опубликовали».
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .models import NewsItem


MAX_CACHE_ITEMS = 200


class NewsCache:
    def __init__(self, cache_path: Path):
        self.cache_path = cache_path

    def save(self, items: list[NewsItem]) -> None:
        now_iso = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
        payload = []
        for it in items[-MAX_CACHE_ITEMS:]:
            d = it.to_dict()
            # collected_at гарантированно проставлен в __post_init__, но если кто-то
            # передал raw dict минуя dataclass — добиваем здесь.
            if not d.get("collected_at"):
                d["collected_at"] = now_iso
            payload.append(d)
        self.cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load(self) -> list[NewsItem]:
        if not self.cache_path.exists():
            return []
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if not isinstance(raw, list):
            return []
        out: list[NewsItem] = []
        for d in raw:
            try:
                out.append(NewsItem.from_dict(d))
            except Exception:
                continue
        return out
