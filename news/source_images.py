"""Stage 12e — NewsSourceImageExtractor.

Достаёт превью-картинку для новости. Приоритет:
1. RSS item: media:content / media:thumbnail / enclosure (если NewsItem или RSS dict).
2. URL статьи: HTML <meta property="og:image"> / "twitter:image" / "article:image"
   / <link rel="image_src">.

Никогда не вызывает OpenAI. Не делает screenshot страницы. Не парсит JS.
Если ничего не нашлось — возвращает None.

Сохраняет картинку в outputs/news_source_images/{news_hash}.{jpg|png|webp}.
"""

from __future__ import annotations

import logging
import mimetypes
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urljoin, urlparse

from .models import NewsItem
from .publisher import news_hash


log = logging.getLogger("news.source_images")


# Stage 12e — какие relation-теги приоритетнее. Перечислены в порядке fallback'а.
META_PROPERTY_PRIORITY = (
    "og:image",
    "og:image:url",
    "og:image:secure_url",
    "twitter:image",
    "twitter:image:src",
    "article:image",
)


_IMAGE_EXT_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/jpg":  ".jpg",
    "image/png":  ".png",
    "image/webp": ".webp",
    "image/gif":  ".gif",
}


class _OgImageHTMLParser(HTMLParser):
    """Минимальный sax-style парсер: ищем <meta property|name="..."> + <link rel="image_src">.

    НЕ грузим стороннюю lxml/bs4 — стандартной библиотеки достаточно для этих
    конкретных тегов. <head> часто содержит весь нужный набор; парсим лениво
    и останавливаемся как только нашли og:image.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        # ключ → значение по приоритету; None если не найдено
        self.values: dict[str, str] = {}
        self.link_image_src: Optional[str] = None
        self._stop_at_body = False

    def handle_starttag(self, tag: str, attrs):  # type: ignore[override]
        if self._stop_at_body:
            return
        attrs = dict(attrs)
        if tag == "meta":
            key = (attrs.get("property") or attrs.get("name") or "").strip().lower()
            content = (attrs.get("content") or "").strip()
            if key and content and key not in self.values:
                self.values[key] = content
        elif tag == "link":
            rel = (attrs.get("rel") or "").strip().lower()
            href = (attrs.get("href") or "").strip()
            if rel == "image_src" and href and not self.link_image_src:
                self.link_image_src = href
        elif tag == "body":
            # за пределами <head> в og обычно ничего нет — парсинг можно ускорить
            self._stop_at_body = True


def _user_agent() -> str:
    # Не маскируемся под бренд, но и не пугаем сервер пустым UA.
    return "Mozilla/5.0 (compatible; ai-deposit-diary-bot/12e; +https://t.me/ai_deposit_diary)"


def _parse_meta_image(html_text: str) -> Optional[str]:
    """Из HTML <head> извлечь image URL по приоритету META_PROPERTY_PRIORITY.

    Возвращает первый найденный URL или None.
    """
    if not html_text:
        return None
    parser = _OgImageHTMLParser()
    try:
        parser.feed(html_text)
    except Exception as e:  # pragma: no cover — защита от очень корявого html
        log.debug("og-parser failed (non-fatal): %s", e)

    for key in META_PROPERTY_PRIORITY:
        v = parser.values.get(key)
        if v:
            return v
    if parser.link_image_src:
        return parser.link_image_src
    return None


def _normalize_image_url(image_url: str, base_url: str) -> str:
    """Превратить относительный URL в абсолютный (если он начинается с / или без схемы)."""
    if not image_url:
        return ""
    if image_url.startswith("//"):
        scheme = urlparse(base_url).scheme or "https"
        return f"{scheme}:{image_url}"
    if image_url.startswith("/") or not urlparse(image_url).scheme:
        return urljoin(base_url, image_url)
    return image_url


def _ext_from_response(content_type: str, url: str) -> str:
    """Угадать расширение для сохранения файла."""
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in _IMAGE_EXT_BY_MIME:
        return _IMAGE_EXT_BY_MIME[ct]
    # из URL по mimetypes
    guess, _ = mimetypes.guess_type(url)
    if guess in _IMAGE_EXT_BY_MIME:
        return _IMAGE_EXT_BY_MIME[guess]
    # последний фолбэк
    return ".jpg"


class NewsSourceImageExtractor:
    """Stage 12e — извлекатель source preview.

    Использование:
        extractor = NewsSourceImageExtractor(save_dir=Path("outputs/news_source_images"))
        path, src_url = extractor.get_source_image(news_item)
        if path: ...
    """

    USER_AGENT = _user_agent()
    HTML_FETCH_TIMEOUT_S = 10
    IMAGE_FETCH_TIMEOUT_S = 15
    MAX_HTML_BYTES = 800_000          # больше — почти наверняка не <head>
    MAX_IMAGE_BYTES = 6 * 1024 * 1024  # 6 MB
    MIN_IMAGE_BYTES = 1024             # < 1 KB — почти точно spacer/tracker

    def __init__(self, save_dir: Path):
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)

    # --- public ---------------------------------------------------------------

    def get_source_image(self, item: NewsItem) -> Tuple[Optional[str], Optional[str]]:
        """Главный entrypoint. Возвращает (local_path_or_None, source_image_url_or_None).

        Никогда не кидает.
        """
        # 1. RSS item — у NewsItem такой структуры нет напрямую; смотрим summary
        #    на признак <img> или <enclosure> (некоторые fetchers их сохраняют).
        rss_image = self.extract_from_rss_item(item)
        if rss_image:
            local = self.download_source_image(rss_image, item)
            if local:
                return (local, rss_image)

        # 2. URL статьи: HTML head → og:image / twitter:image / article:image
        if item.url:
            try:
                meta_image = self.extract_from_url(item.url)
            except Exception as e:
                log.warning("source-image: extract_from_url failed (%s): %s", item.url, e)
                meta_image = None
            if meta_image:
                local = self.download_source_image(meta_image, item)
                if local:
                    return (local, meta_image)

        return (None, None)

    def extract_from_rss_item(self, item: NewsItem) -> Optional[str]:
        """Поиск картинки в данных RSS-фида (best-effort).

        NewsItem в этом проекте уже compacted и не сохраняет media:content;
        но если в summary есть <img src="..."> — уберём первый встретившийся.
        """
        summary = (item.summary or "")[:8000]
        if not summary:
            return None
        m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary, re.IGNORECASE)
        if m:
            url = m.group(1).strip()
            if url and not self._looks_like_tracker(url):
                return self._absolute_or_self(url, item.url)
        # на некоторых сайтах в summary может прилететь <enclosure url="...">
        m2 = re.search(r'<enclosure[^>]+url=["\']([^"\']+)["\']', summary, re.IGNORECASE)
        if m2:
            url = m2.group(1).strip()
            if url and not self._looks_like_tracker(url):
                return self._absolute_or_self(url, item.url)
        return None

    def extract_from_url(self, url: str) -> Optional[str]:
        """GET страницы и поиск meta-image в <head>. Только http/https, без редиректа на data:."""
        if not url or not urlparse(url).scheme.startswith("http"):
            return None

        import urllib.request
        req = urllib.request.Request(
            url,
            headers={"User-Agent": self.USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.HTML_FETCH_TIMEOUT_S) as resp:
                ct = (resp.headers.get("Content-Type") or "").lower()
                if "html" not in ct and "xml" not in ct:
                    log.info("source-image: skipping %s (content-type %s)", url, ct)
                    return None
                raw = resp.read(self.MAX_HTML_BYTES)
        except Exception as e:
            log.info("source-image: HTML fetch failed for %s: %s", url, e)
            return None

        # Декодируем максимально безопасно — если encoding из заголовка нет, считаем utf-8 with replace
        text = self._decode_html(raw, ct)
        meta = _parse_meta_image(text)
        if not meta:
            return None
        if self._looks_like_tracker(meta) or meta.startswith("data:"):
            return None
        return _normalize_image_url(meta, url)

    def download_source_image(self, image_url: str, item: NewsItem) -> Optional[str]:
        """Скачать картинку и сохранить как outputs/news_source_images/{news_hash}.<ext>.

        Возвращает локальный path как str или None при любой ошибке.
        """
        if not image_url:
            return None
        try:
            import urllib.request
            req = urllib.request.Request(
                image_url,
                headers={
                    "User-Agent": self.USER_AGENT,
                    "Accept": "image/jpeg,image/png,image/webp,image/*;q=0.8,*/*;q=0.5",
                    "Referer": item.url or "",
                },
            )
            with urllib.request.urlopen(req, timeout=self.IMAGE_FETCH_TIMEOUT_S) as resp:
                ct = resp.headers.get("Content-Type") or ""
                if not ct.lower().startswith("image/"):
                    log.info("source-image: not an image (ct=%s) for %s", ct, image_url)
                    return None
                size_hint = resp.headers.get("Content-Length")
                if size_hint and int(size_hint) > self.MAX_IMAGE_BYTES:
                    log.info("source-image: too big (%s bytes), skip", size_hint)
                    return None
                blob = resp.read(self.MAX_IMAGE_BYTES + 1)
        except Exception as e:
            log.info("source-image: download failed for %s: %s", image_url, e)
            return None

        if len(blob) < self.MIN_IMAGE_BYTES:
            log.info("source-image: too small (%d bytes) — likely tracker, skip", len(blob))
            return None
        if len(blob) > self.MAX_IMAGE_BYTES:
            log.info("source-image: exceeded max size (%d bytes), skip", len(blob))
            return None

        ext = _ext_from_response(ct, image_url)
        out_path = self.save_dir / f"{news_hash(item)}{ext}"
        try:
            out_path.write_bytes(blob)
        except OSError as e:
            log.warning("source-image: cannot write %s: %s", out_path, e)
            return None
        log.info("source-image: saved %s (%d bytes)", out_path.name, len(blob))
        return str(out_path)

    # --- helpers --------------------------------------------------------------

    @staticmethod
    def _looks_like_tracker(url: str) -> bool:
        """Эвристика: спейсер 1×1 / pixel-tracker."""
        u = (url or "").lower()
        if not u:
            return True
        if any(x in u for x in ("/spacer.gif", "1x1.gif", "pixel.gif", "pixel.png", "/blank.gif")):
            return True
        if "tracking" in u and any(x in u for x in (".gif", ".png")):
            return True
        return False

    @staticmethod
    def _absolute_or_self(url: str, base_url: str) -> str:
        if url.startswith(("http://", "https://", "//")):
            return _normalize_image_url(url, base_url or "https://example.com")
        if base_url:
            return _normalize_image_url(url, base_url)
        return url

    @staticmethod
    def _decode_html(raw: bytes, content_type: str) -> str:
        # extract charset из content-type
        m = re.search(r"charset=([\w\-]+)", content_type or "", re.IGNORECASE)
        if m:
            try:
                return raw.decode(m.group(1).strip(), errors="replace")
            except LookupError:
                pass
        # дефолт
        try:
            return raw.decode("utf-8", errors="replace")
        except Exception:
            return raw.decode("latin-1", errors="replace")
