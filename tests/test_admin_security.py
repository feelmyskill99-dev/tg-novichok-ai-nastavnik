"""Этап 1.5: безопасность админки.

Покрытие:
- fail-fast при отсутствии/changeme ADMIN_PASSWORD
- secrets.compare_digest вместо ==
- bind 127.0.0.1 по умолчанию, 0.0.0.0 только явным флагом
- HTML sanitize/escape для draft_text в /admin/force_post
- CSRF token обязателен для POST
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _reload_admin(monkeypatch: pytest.MonkeyPatch, **env: str):
    """Перезагружает admin_panel с заданными env-переменными.

    Подменяет dotenv.load_dotenv на no-op, чтобы реальный .env не переезжал
    monkeypatch-нутые значения.
    """
    monkeypatch.setenv("TELEGRAM_TOKEN", env.get("TELEGRAM_TOKEN", "test:token"))
    monkeypatch.setenv("OWNER_CHAT_ID", env.get("OWNER_CHAT_ID", "123"))
    monkeypatch.setenv("CHANNEL_ID", env.get("CHANNEL_ID", "@test"))
    if "ADMIN_PASSWORD" in env:
        monkeypatch.setenv("ADMIN_PASSWORD", env["ADMIN_PASSWORD"])
    else:
        monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("ADMIN_USERNAME", env.get("ADMIN_USERNAME", "admin"))

    import dotenv as _dotenv
    monkeypatch.setattr(_dotenv, "load_dotenv", lambda *a, **kw: True)

    sys.modules.pop("admin_panel", None)
    return importlib.import_module("admin_panel")


def test_fails_fast_without_admin_password(monkeypatch: pytest.MonkeyPatch):
    """Без ADMIN_PASSWORD — _ensure_password_set должен бросать.

    Сам импорт admin_panel разрешён (чтобы bot.py CLI работал), но любой
    реальный hit на /admin или старт uvicorn вызывает _ensure_password_set.
    """
    mod = _reload_admin(monkeypatch)
    with pytest.raises(RuntimeError):
        mod._ensure_password_set()


def test_fails_fast_on_default_changeme(monkeypatch: pytest.MonkeyPatch):
    """ADMIN_PASSWORD=changeme — недопустимо."""
    mod = _reload_admin(monkeypatch, ADMIN_PASSWORD="changeme")
    with pytest.raises(RuntimeError):
        mod._ensure_password_set()


def test_dashboard_rejected_when_password_unset(monkeypatch: pytest.MonkeyPatch):
    """Запрос на /admin без сильного пароля должен отклоняться."""
    from fastapi.testclient import TestClient

    mod = _reload_admin(monkeypatch)  # без ADMIN_PASSWORD
    client = TestClient(mod.app, raise_server_exceptions=False)

    resp = client.get("/admin", auth=("admin", "anything"))
    assert resp.status_code in (401, 500), (
        f"Доступ к /admin без сильного пароля недопустим, status={resp.status_code}"
    )


def test_strong_password_starts_ok(monkeypatch: pytest.MonkeyPatch):
    mod = _reload_admin(monkeypatch, ADMIN_PASSWORD="s3cret!Strong#42")
    assert mod.app is not None


def test_uses_compare_digest(monkeypatch: pytest.MonkeyPatch):
    """admin_panel.py должен использовать secrets.compare_digest, не ==."""
    src = (ROOT / "admin_panel.py").read_text(encoding="utf-8")
    assert "compare_digest" in src, (
        "admin_panel.py должен использовать secrets.compare_digest для пароля"
    )


def test_default_bind_is_localhost(monkeypatch: pytest.MonkeyPatch):
    """uvicorn.run в __main__ должен по умолчанию слушать 127.0.0.1, не 0.0.0.0."""
    src = (ROOT / "admin_panel.py").read_text(encoding="utf-8")
    # Жёсткий 0.0.0.0 не должен быть default-ом
    import re
    main_block = re.search(r'if __name__ == "__main__":(.*)', src, re.DOTALL)
    assert main_block, "__main__ блок не найден"
    body = main_block.group(1)
    assert '"0.0.0.0"' not in body or "ADMIN_BIND_PUBLIC" in body or "ADMIN_HOST" in body, (
        "Default host должен быть 127.0.0.1 (0.0.0.0 — только через явный env-флаг)"
    )


def test_force_post_requires_csrf_token(monkeypatch: pytest.MonkeyPatch):
    """POST /admin/force_post без CSRF-токена должен отвергаться (403)."""
    from fastapi.testclient import TestClient

    mod = _reload_admin(monkeypatch, ADMIN_PASSWORD="s3cret!Strong#42")
    client = TestClient(mod.app)

    resp = client.post(
        "/admin/force_post",
        data={"post_type": "education", "draft_text": "hi"},
        auth=("admin", "s3cret!Strong#42"),
    )
    assert resp.status_code in (400, 403), (
        f"POST без CSRF должен отвергаться, получили {resp.status_code}"
    )


def test_force_post_sanitizes_dangerous_html(monkeypatch: pytest.MonkeyPatch):
    """draft_text не должен попадать в send_message с произвольным HTML.

    Проверяем через капчу: подменим bot.send_message на коллектор и убедимся,
    что переданный текст НЕ содержит сырых <script>...</script>.
    """
    from fastapi.testclient import TestClient

    mod = _reload_admin(monkeypatch, ADMIN_PASSWORD="s3cret!Strong#42")
    client = TestClient(mod.app)

    captured: dict = {}

    class _FakeBot:
        def __init__(self) -> None:
            self.session = _FakeSession()

        async def send_message(self, chat_id, text, **kw):
            captured["text"] = text

    class _FakeSession:
        async def close(self):
            pass

    monkeypatch.setattr(mod, "get_bot", lambda: _FakeBot())

    # Сначала GET /admin, чтобы получить CSRF-токен (если есть).
    get_resp = client.get("/admin", auth=("admin", "s3cret!Strong#42"))
    assert get_resp.status_code == 200, get_resp.text

    import re
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', get_resp.text)
    csrf = m.group(1) if m else ""

    payload = {
        "post_type": "education",
        "draft_text": "<script>alert(1)</script><b>ok</b>",
        "csrf_token": csrf,
    }
    resp = client.post(
        "/admin/force_post",
        data=payload,
        auth=("admin", "s3cret!Strong#42"),
        cookies=get_resp.cookies,
    )
    assert resp.status_code == 200, f"Failed: {resp.status_code} {resp.text}"

    sent = captured.get("text", "")
    assert "<script>" not in sent, (
        f"Sanitize не сработал — отправлен сырой <script>. text={sent!r}"
    )
