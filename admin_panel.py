"""Админ-панель (этап 1.5 — безопасный минимум).

Изменения:
- fail-fast при отсутствии/слабом ADMIN_PASSWORD
- secrets.compare_digest для проверки credentials
- по умолчанию bind на 127.0.0.1; 0.0.0.0 только при ADMIN_BIND_PUBLIC=true
- HTML sanitize (allowlist b/i/code/a) для draft_text в /admin/force_post
- CSRF token: double-submit (cookie + form-field), обязателен для POST
"""
from __future__ import annotations

import html as html_lib
import json
import os
import re
import secrets
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID")
CHANNEL_ID = os.getenv("CHANNEL_ID")
ADMIN_USER = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASSWORD", "")

# --- fail-fast: пустой или дефолтный пароль не допускается ----------------
# Проверка вызывается ДО старта uvicorn и при первом hit на /admin.
# Сам импорт admin_panel (из bot.py) не падает, чтобы CLI-команды бота работали
# даже без ADMIN_PASSWORD.
_FORBIDDEN_PASSWORDS = {"", "changeme", "admin", "password", "1234"}


def _ensure_password_set() -> None:
    if ADMIN_PASS.strip().lower() in _FORBIDDEN_PASSWORDS:
        raise RuntimeError(
            "ADMIN_PASSWORD не задан или слишком слабый. "
            "Задайте сильный пароль в .env (минимум 12 символов, не 'changeme')."
        )


CSRF_COOKIE = "admin_csrf"
mistake_tracker = None  # выставляется из bot.py


from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
import aiohttp


app = FastAPI(title="AI Наставник — Панель управления")
security = HTTPBasic()


def get_bot():
    if not TELEGRAM_TOKEN:
        return None
    session = AiohttpSession()
    session._connector_init["resolver"] = aiohttp.ThreadedResolver()
    return Bot(token=TELEGRAM_TOKEN, session=session)


def authenticate(credentials: HTTPBasicCredentials = Depends(security)) -> bool:
    _ensure_password_set()
    user_ok = secrets.compare_digest(
        credentials.username.encode("utf-8"), ADMIN_USER.encode("utf-8")
    )
    pass_ok = secrets.compare_digest(
        credentials.password.encode("utf-8"), ADMIN_PASS.encode("utf-8")
    )
    if not (user_ok and pass_ok):
        raise HTTPException(status_code=401, detail="Not authorized")
    return True


def _new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def _verify_csrf(request: Request, form_token: str) -> None:
    cookie_token = request.cookies.get(CSRF_COOKIE, "")
    if not cookie_token or not form_token:
        raise HTTPException(status_code=403, detail="CSRF token missing")
    if not secrets.compare_digest(cookie_token.encode(), form_token.encode()):
        raise HTTPException(status_code=403, detail="CSRF token mismatch")


# Этап 2.4 шаг 3: sanitize_telegram_html теперь живёт в core/html_safe.
# Тут — re-export для existing callers / tests.
from core.html_safe import sanitize_telegram_html  # noqa: F401, E402


# ----------------- Контент-микс (read-only render) -----------------
def get_content_mix_html() -> str:
    """Рендер 7-дневной статистики. Логика — в core.content_mix.compute_mix."""
    from core.content_mix import compute_mix

    state_file = ROOT / "state.json"
    if not state_file.exists():
        return "<p>Нет данных state.json. Бот ещё не накопил историю.</p>"
    try:
        data = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception as e:
        return f"<p>Ошибка чтения state.json: {html_lib.escape(str(e))}</p>"

    log_list = data.get("content_mix_log", [])
    if not log_list:
        return "<p>Контент-микс лог пуст. Данные накопятся после нескольких публикаций.</p>"

    res = compute_mix(log_list)
    target = res["target"]
    shares = res["shares"]

    rows = ""
    for cat in target:
        pct = int(shares.get(cat, 0.0) * 100)
        tgt = int(target[cat] * 100)
        rows += f"<tr><td>{cat}</td><td>{pct}%</td><td>{tgt}%</td></tr>"

    return f"""
    <div class="card">
        <h3>📊 Контент-микс (7 дней)</h3>
        <table>
            <tr><th>Категория</th><th>Сейчас</th><th>Цель</th></tr>
            {rows}
        </table>
        <p><strong>Режим:</strong> {res["mode"]}, всего постов: {res["total_posts"]}</p>
        <p><strong>Рекомендуемый тип:</strong> {res["recommended"]}</p>
        <p><em>{html_lib.escape(res["reason"])}</em></p>
    </div>
    """


def get_mistake_report() -> str:
    tracker_state = ROOT / "mistake_tracker_state.json"
    if not tracker_state.exists():
        return "Нет данных трекера ошибок."
    try:
        from core.mistake_tracker import MistakeTracker
        tracker = MistakeTracker(
            themes_file=str(ROOT / "mistake_themes.json"),
            state_file=str(tracker_state)
        )
        return tracker.weekly_report()
    except Exception as e:
        return f"Ошибка: {html_lib.escape(str(e))}"


# ================== Главная страница ==================
@app.get("/admin", response_class=HTMLResponse)
async def dashboard(request: Request, auth=Depends(authenticate)):
    content_mix_html = get_content_mix_html()
    mistake_report = get_mistake_report()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    csrf_token = request.cookies.get(CSRF_COOKIE) or _new_csrf_token()

    page = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>AI Наставник — Панель управления</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
    body {{ font-family: 'Segoe UI', sans-serif; margin: 2em; background: #1a1a2e; color: #eee; }}
    .container {{ max-width: 800px; margin: auto; }}
    .card {{ background: #16213e; padding: 1em; border-radius: 8px; margin-bottom: 1em; }}
    button {{ background: #e94560; color: white; border: none; padding: 0.7em 1.4em; border-radius: 5px; margin: 0.3em; cursor: pointer; }}
    button.active {{ background: #ff6b6b; }}
    textarea {{ width: 100%; margin-top: 1em; background: #0f3460; color: white; border: 1px solid #e94560; padding: 0.5em; border-radius: 5px; }}
    .success {{ background: #1b4332; color: #b7e4c7; padding: 0.5em; border-radius: 5px; }}
    .error {{ background: #5c1a1a; color: #f8d7da; padding: 0.5em; border-radius: 5px; }}
    pre {{ white-space: pre-wrap; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #e94560; padding: 6px; text-align: center; }}
</style>
</head>
<body>
<div class="container">
    <h1>🧠 Пульт AI-Наставника</h1>
    {content_mix_html}

    <div class="card">
        <h3>🧠 Mistake Tracker — еженедельный отчёт</h3>
        <pre>{html_lib.escape(mistake_report)}</pre>
    </div>

    <div class="card">
        <h3>Принудительная публикация</h3>
        <form id="postForm">
            <input type="hidden" name="csrf_token" value="{csrf_token}">
            <label>Тип поста:</label><br>
            <button type="button" class="type-btn" onclick="changeType('market', this)">📈 Рынок</button>
            <button type="button" class="type-btn" onclick="changeType('news', this)">📰 Новости</button>
            <button type="button" class="type-btn" onclick="changeType('education', this)">📘 Обучение</button>
            <br><br>
            <input type="hidden" id="postType" name="post_type" value="education">
            <label>Или вставьте свой текст (HTML-allowlist: b/i/code/a):</label><br>
            <textarea id="draftText" name="draft_text" rows="6" placeholder="Введите текст поста..."></textarea><br>
            <button type="button" onclick="submitForm()">🚀 Отправить в канал</button>
        </form>
        <div id="msg"></div>
    </div>

    <p style="text-align:right; font-size:small;">Канал: {html_lib.escape(CHANNEL_ID or "—")} | Обновлено: {now_str}</p>
</div>
<script>
    window.changeType = function(type, btn) {{
        document.getElementById('postType').value = type;
        var buttons = document.querySelectorAll('.type-btn');
        buttons.forEach(function(b) {{ b.classList.remove('active'); }});
        btn.classList.add('active');
    }};

    window.submitForm = function() {{
        var form = document.getElementById('postForm');
        var formData = new FormData(form);
        var msgDiv = document.getElementById('msg');
        fetch('/admin/force_post', {{
            method: 'POST',
            body: formData
        }})
        .then(function(resp) {{ return resp.json(); }})
        .then(function(data) {{
            if (data.status === 'ok') {{
                msgDiv.className = 'success';
                msgDiv.textContent = '✅ ' + data.detail;
            }} else {{
                msgDiv.className = 'error';
                msgDiv.textContent = '❌ ' + data.detail;
            }}
            document.getElementById('draftText').value = '';
        }})
        .catch(function(err) {{
            msgDiv.className = 'error';
            msgDiv.textContent = '❌ Ошибка: ' + err;
        }});
    }};

    var initial = document.querySelector('.type-btn[onclick*="education"]');
    if (initial) initial.classList.add('active');
</script>
</body>
</html>"""
    response = HTMLResponse(content=page)
    response.set_cookie(
        CSRF_COOKIE, csrf_token,
        httponly=False, samesite="strict", max_age=3600,
    )
    return response


@app.post("/admin/force_post")
async def force_post(
    request: Request,
    post_type: str = Form(...),
    draft_text: str = Form(""),
    csrf_token: str = Form(""),
    auth=Depends(authenticate),
):
    _verify_csrf(request, csrf_token)

    bot_instance = get_bot()
    if not bot_instance or not CHANNEL_ID:
        return {"status": "error", "detail": "Bot not configured"}
    try:
        if draft_text.strip():
            safe = sanitize_telegram_html(draft_text)
            await bot_instance.send_message(CHANNEL_ID, safe, parse_mode="HTML")
            await bot_instance.session.close()
            return {"status": "ok", "detail": f"Custom post published as {post_type}"}
        await bot_instance.send_message(
            CHANNEL_ID,
            "Публикация через админку (без своего текста) пока не реализована.",
        )
        await bot_instance.session.close()
        return {"status": "ok", "detail": "Fallback message sent."}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


if __name__ == "__main__":
    import uvicorn

    _ensure_password_set()
    public = os.getenv("ADMIN_BIND_PUBLIC", "false").strip().lower() in ("1", "true", "yes")
    host = "0.0.0.0" if public else "127.0.0.1"
    uvicorn.run(app, host=host, port=8000, log_level="info")
