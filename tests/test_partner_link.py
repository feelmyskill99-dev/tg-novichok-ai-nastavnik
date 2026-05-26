"""build_partner_url — UTM-метки к партнёрской ссылке."""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.partner_link import build_partner_url


def _qs(url: str) -> dict[str, str]:
    qs = parse_qs(urlparse(url).query, keep_blank_values=True)
    return {k: v[0] for k, v in qs.items()}


def test_adds_utm_source_medium_to_bare_url():
    out = build_partner_url("https://gate.io/", post_type="market")
    qs = _qs(out)
    assert qs["utm_source"] == "tg_ai_deposit"
    assert qs["utm_medium"] == "market"
    assert "utm_content" not in qs


def test_adds_utm_content_when_post_id_set():
    out = build_partner_url("https://gate.io/", post_type="news", post_id="abc123")
    qs = _qs(out)
    assert qs["utm_content"] == "abc123"
    assert qs["utm_medium"] == "news"


def test_preserves_existing_ref_param():
    """Реф-ссылка Gate.io обычно содержит ?ref=XXX — её надо сохранить."""
    out = build_partner_url("https://gate.io/signup/REFXYZ?ref=REFXYZ", post_type="market")
    qs = _qs(out)
    assert qs["ref"] == "REFXYZ"
    assert qs["utm_source"] == "tg_ai_deposit"


def test_overwrites_existing_utm():
    """Если URL уже помечен — новые UTM перезаписывают старые, без дубля знака ?."""
    out = build_partner_url(
        "https://gate.io/?utm_source=old&utm_medium=banner",
        post_type="news",
    )
    qs = _qs(out)
    assert qs["utm_source"] == "tg_ai_deposit"
    assert qs["utm_medium"] == "news"
    assert out.count("?") == 1   # ни в коем случае не https://gate.io/??...


def test_empty_url_returns_empty():
    assert build_partner_url("", post_type="market") == ""
    assert build_partner_url("   ", post_type="market") == ""


def test_default_post_type_is_post():
    out = build_partner_url("https://gate.io/")
    qs = _qs(out)
    assert qs["utm_medium"] == "post"


def test_handles_url_with_path_and_fragment():
    """Path и fragment не теряются."""
    out = build_partner_url(
        "https://www.gate.io/signup/12345?ref=ABC#section",
        post_type="pinned",
        post_id="welcome",
    )
    parsed = urlparse(out)
    assert parsed.netloc == "www.gate.io"
    assert parsed.path == "/signup/12345"
    assert parsed.fragment == "section"
    qs = _qs(out)
    assert qs["ref"] == "ABC"
    assert qs["utm_medium"] == "pinned"
    assert qs["utm_content"] == "welcome"
