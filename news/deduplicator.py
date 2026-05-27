"""NewsDeduplicator — не публикуем одну и ту же новость дважды.

История хранится в news_history.json. Дедуплицируем по:
    - совпадению нормализованного title_hash за последние 48 часов
    - совпадению URL (в тот же период)
    - похожести заголовка по difflib.SequenceMatcher (порог TITLE_SIMILARITY_THRESHOLD)
      — ловит ту же новость из другого источника
"""

from __future__ import annotations

import difflib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dateutil import parser as dtparser

from .models import NewsItem


log = logging.getLogger("news.dedup")

DEFAULT_WINDOW_HOURS = 48
MAX_HISTORY_RECORDS = 500

# Stage 12g — кросс-источниковый дедуп. Если нормализованный заголовок новой новости
# похож на исторический ≥ 65%, считаем дубликатом. Подобрано эмпирически: режет
# случаи «одна новость в Decrypt vs CoinDesk» (обычно ratio 0.7+), но пропускает
# слабо связанные новости с общими словами (обычно ratio < 0.55).
TITLE_SIMILARITY_THRESHOLD = 0.65

# Стопворды + общие крипто-токены, которые не должны влиять на сравнение.
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "to", "of", "in", "on",
    "for", "and", "or", "but", "with", "as", "at", "by", "from", "after",
    "says", "could", "will", "would", "may", "might", "amid", "over", "into",
    "что", "это", "как", "для", "из", "от", "на", "по", "за", "под", "над",
    "и", "или", "но", "а", "же", "уже", "ещё", "не", "же",
}


def _tokenize_title(title: str) -> str:
    """Нормализация заголовка для сравнения: lowercase, убираем пунктуацию,
    стопворды, числа короче 4 цифр (год оставляем, '5%' и '300m' выкидываем).

    Возвращает строку из отсортированных токенов через пробел — годится
    как для difflib, так и для будущего хэша.
    """
    if not title:
        return ""
    s = title.lower()
    s = re.sub(r"[^\w\s]+", " ", s, flags=re.UNICODE)
    tokens = []
    for tok in s.split():
        if tok in _STOPWORDS:
            continue
        if tok.isdigit() and len(tok) < 4:
            continue
        if len(tok) <= 2:
            continue
        tokens.append(tok)
    return " ".join(sorted(tokens))


class NewsDeduplicator:
    def __init__(self, history_path: Path, window_hours: int = DEFAULT_WINDOW_HOURS):
        self.history_path = history_path
        self.window_hours = window_hours

    def _load(self) -> list[dict]:
        if not self.history_path.exists():
            return []
        try:
            raw = json.loads(self.history_path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, list) else []
        except Exception as e:
            log.warning("news_history.json повреждён: %s", e)
            return []

    def _save(self, records: list[dict]) -> None:
        self.history_path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def is_duplicate(self, item: NewsItem) -> bool:
        records = self._load()
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=self.window_hours)
        item_tokens = _tokenize_title(item.title)
        for rec in records:
            try:
                dt = dtparser.parse(rec.get("posted_at", ""))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt < cutoff:
                    continue
            except Exception:
                continue
            if rec.get("title_hash") == item.id:
                return True
            if rec.get("url") and rec["url"] == item.url:
                return True
            # Stage 12g — кросс-источниковая похожесть. Сравниваем нормализованные
            # токены через difflib; быстро (заголовков мало, ratio O(n*m) на словах).
            rec_title = rec.get("title") or ""
            if rec_title and item_tokens:
                rec_tokens = _tokenize_title(rec_title)
                if rec_tokens:
                    ratio = difflib.SequenceMatcher(None, item_tokens, rec_tokens).ratio()
                    if ratio >= TITLE_SIMILARITY_THRESHOLD:
                        log.info(
                            "dedup similar (%.2f): new=%r vs history=%r [%s]",
                            ratio, item.title[:80], rec_title[:80], rec.get("source", "?"),
                        )
                        return True
        return False

    def remember(
        self,
        item: NewsItem,
        decision: str,
        *,
        short_summary: str = "",
    ) -> None:
        """decision ∈ {'published_channel', 'sent_owner', 'skipped', 'claude_rejected'}.

        short_summary — однострочное описание из ответа Claude, помогает позже понять
        «о чём была эта новость» без открытия URL.
        """
        records = self._load()
        records.append({
            "title_hash": item.id,
            "title": item.title,
            "url": item.url,
            "source": item.source,
            "posted_at": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
            "impact_score": item.impact_score,
            "sector": item.sector,
            "decision": decision,
            "short_summary": short_summary,
        })
        # ограничим rolling-size, чтобы файл не рос бесконечно
        records = records[-MAX_HISTORY_RECORDS:]
        self._save(records)

    def posted_today(self, *, only_channel: bool = False) -> int:
        """Сколько новостных постов уже ушло сегодня (UTC)."""
        records = self._load()
        today = datetime.now(tz=timezone.utc).date()
        count = 0
        for rec in records:
            try:
                dt = dtparser.parse(rec.get("posted_at", ""))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if dt.date() != today:
                continue
            if only_channel and rec.get("decision") != "published_channel":
                continue
            if rec.get("decision") in ("skipped", "claude_rejected"):
                continue
            count += 1
        return count

    def posted_today_in_sector(self, sector: str, *, only_channel: bool = False) -> int:
        """Сколько постов конкретного sector'а уже ушло сегодня (UTC).

        Защищает от перекоса в один день (27.04: 4 stablecoin-поста подряд).
        """
        if not sector:
            return 0
        records = self._load()
        today = datetime.now(tz=timezone.utc).date()
        count = 0
        for rec in records:
            if rec.get("sector") != sector:
                continue
            try:
                dt = dtparser.parse(rec.get("posted_at", ""))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if dt.date() != today:
                continue
            if only_channel and rec.get("decision") != "published_channel":
                continue
            if rec.get("decision") in ("skipped", "claude_rejected"):
                continue
            count += 1
        return count
