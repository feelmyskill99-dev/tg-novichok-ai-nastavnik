"""NewsCollector — собирает новости из RSS / CryptoPanic / CoinMarketCal.

RSS работает всегда. API-источники — только если соответствующий ключ задан.
Никакого HTML-парсинга сайтов.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import feedparser
import httpx
from dateutil import parser as dtparser

from .config import NewsConfig
from .models import NewsItem


log = logging.getLogger("news.collector")


RSS_FEEDS = {
    "CoinDesk":      "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Cointelegraph": "https://cointelegraph.com/rss",
    "Decrypt":       "https://decrypt.co/feed",
    "The Block":     "https://www.theblock.co/rss.xml",
}

HTTP_TIMEOUT = 15.0
MAX_PER_SOURCE = 50


class NewsCollector:
    def __init__(self, config: NewsConfig):
        self.cfg = config

    async def collect(self) -> list[NewsItem]:
        tasks = [self._collect_rss()]
        if self.cfg.cryptopanic_api_key:
            tasks.append(self._collect_cryptopanic())
        if self.cfg.coinmarketcal_api_key:
            tasks.append(self._collect_coinmarketcal())

        results = await asyncio.gather(*tasks, return_exceptions=True)
        items: list[NewsItem] = []
        for r in results:
            if isinstance(r, Exception):
                log.warning("news source failed: %s", r)
                continue
            items.extend(r)

        return self._filter_by_lookback(items)

    # ---------- RSS ----------
    async def _collect_rss(self) -> list[NewsItem]:
        out: list[NewsItem] = []
        for source, url in RSS_FEEDS.items():
            try:
                parsed = await asyncio.to_thread(feedparser.parse, url)
            except Exception as e:
                log.warning("RSS %s failed: %s", source, e)
                continue
            for entry in (parsed.entries or [])[:MAX_PER_SOURCE]:
                title = (entry.get("title") or "").strip()
                link = (entry.get("link") or "").strip()
                if not title or not link:
                    continue
                summary = (entry.get("summary") or "").strip()
                published = entry.get("published") or entry.get("updated") or ""
                published_iso = _to_iso_utc(published)
                out.append(NewsItem(
                    title=title,
                    url=link,
                    source=source,
                    published_at=published_iso,
                    summary=summary,
                ))
        return out

    # ---------- CryptoPanic ----------
    async def _collect_cryptopanic(self) -> list[NewsItem]:
        url = "https://cryptopanic.com/api/v1/posts/"
        params = {
            "auth_token": self.cfg.cryptopanic_api_key,
            "filter": "hot",
            "kind": "news",
            "public": "true",
        }
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                r = await client.get(url, params=params)
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            log.warning("CryptoPanic failed: %s", e)
            return []

        out: list[NewsItem] = []
        posts = data.get("results") if isinstance(data, dict) else []
        for post in (posts or [])[:MAX_PER_SOURCE]:
            title = (post.get("title") or "").strip()
            link = post.get("url") or ""
            if not title or not link:
                continue
            source_name = ((post.get("source") or {}).get("title") or "CryptoPanic").strip()
            published = post.get("published_at") or ""
            assets = [
                (c.get("code") or "").upper()
                for c in (post.get("currencies") or [])
                if c.get("code")
            ]
            votes = post.get("votes") or {}
            # votes.important и votes.positive/negative — сигнал «важности» от сообщества
            raw_importance = _scale_0_1(
                int(votes.get("important") or 0)
                + int(votes.get("positive") or 0)
                + int(votes.get("negative") or 0),
                ceiling=50,
            )
            out.append(NewsItem(
                title=title,
                url=link,
                source=source_name,
                published_at=_to_iso_utc(published),
                assets=assets,
                raw_importance=raw_importance,
            ))
        return out

    # ---------- CoinMarketCal ----------
    async def _collect_coinmarketcal(self) -> list[NewsItem]:
        url = "https://api.coinmarketcal.com/v2/events"
        headers = {
            "x-api-key": self.cfg.coinmarketcal_api_key,
            "Accept-Encoding": "deflate, gzip",
            "Accept": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                r = await client.get(url, headers=headers, params={"max": MAX_PER_SOURCE})
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            log.warning("CoinMarketCal failed: %s", e)
            return []

        body = data.get("body") if isinstance(data, dict) else data
        out: list[NewsItem] = []
        for event in (body or [])[:MAX_PER_SOURCE]:
            title_raw = event.get("title")
            if isinstance(title_raw, dict):
                title = (title_raw.get("en") or "").strip()
            else:
                title = (title_raw or "").strip()
            if not title:
                continue
            link = event.get("proof") or event.get("source") or ""
            if not link:
                continue
            published = event.get("created_date") or event.get("date_event") or ""
            coins = event.get("coins") or []
            assets: list[str] = []
            for c in coins:
                if isinstance(c, dict):
                    sym = c.get("symbol") or c.get("fullname") or ""
                    if sym:
                        assets.append(sym.upper())

            votes = event.get("percentage") or event.get("vote_count") or 0
            try:
                raw_importance = _scale_0_1(float(votes), ceiling=100)
            except (TypeError, ValueError):
                raw_importance = 0.0

            out.append(NewsItem(
                title=title,
                url=link,
                source="CoinMarketCal",
                published_at=_to_iso_utc(published),
                assets=assets,
                raw_importance=raw_importance,
            ))
        return out

    # ---------- lookback ----------
    def _filter_by_lookback(self, items: list[NewsItem]) -> list[NewsItem]:
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=self.cfg.news_lookback_hours)
        out: list[NewsItem] = []
        for item in items:
            try:
                dt = dtparser.parse(item.published_at)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt >= cutoff:
                    out.append(item)
            except Exception:
                continue
        return out


# =============================================================================
# helpers
# =============================================================================

def _to_iso_utc(raw: str) -> str:
    if not raw:
        return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
    try:
        dt = dtparser.parse(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt.isoformat(timespec="seconds")
    except Exception:
        return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def _scale_0_1(value: float, ceiling: float) -> float:
    if ceiling <= 0:
        return 0.0
    v = max(0.0, min(float(value), ceiling)) / ceiling
    return round(v, 4)
