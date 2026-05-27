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


def get_engagement_report() -> str:
    """Топ-5 постов по реакциям из state.json.post_engagement."""
    try:
        from core.json_store import load_json
        from core.post_engagement import top_posts_by_engagement, total_reaction_count
        state = load_json(ROOT / "state.json", default={}, expected_type=dict)
        engagement = state.get("post_engagement") or {}
        total = total_reaction_count(engagement)
        if total == 0:
            return "Реакций пока не зафиксировано (бот должен быть admin канала и polling должен включать message_reaction)."
        top = top_posts_by_engagement(engagement, limit=5)
        lines = [f"Всего реакций: {total} · отслеживается {len(engagement)} постов", ""]
        for i, (key, entry, score) in enumerate(top, 1):
            msg_id = entry.get("message_id", "?")
            reactions = entry.get("reactions") or {}
            top_emoji = sorted(reactions.items(), key=lambda kv: kv[1], reverse=True)[:3]
            emoji_str = " ".join(f"{e}×{c}" for e, c in top_emoji)
            updated = entry.get("last_updated_at", "")[:16].replace("T", " ")
            lines.append(f"{i}. msg #{msg_id} — {score} реакций ({emoji_str}) [{updated}]")
        return "\n".join(lines)
    except Exception as e:
        return f"Ошибка: {html_lib.escape(str(e))}"


# ================== Главная страница ==================
@app.get("/admin", response_class=HTMLResponse)
async def dashboard(request: Request, auth=Depends(authenticate)):
    content_mix_html = get_content_mix_html()
    mistake_report = get_mistake_report()
    engagement_report = get_engagement_report()
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
    <p><a href="/admin/queue" style="color:#e94560">📥 Очередь черновиков (review)</a></p>
    {content_mix_html}

    <div class="card">
        <h3>🧠 Mistake Tracker — еженедельный отчёт</h3>
        <pre>{html_lib.escape(mistake_report)}</pre>
    </div>

    <div class="card">
        <h3>💬 Engagement — топ постов по реакциям</h3>
        <pre>{html_lib.escape(engagement_report)}</pre>
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


# ================== Bulk-review очереди ==================
NEWS_DRAFTS_FILE = ROOT / "news_drafts.json"
AUTHOR_NOTES_FILE = ROOT / "author_notes_drafts.json"


def _list_pending_news() -> list:
    try:
        from news.drafts import DraftStore
        return DraftStore(NEWS_DRAFTS_FILE).list_pending()
    except Exception:
        return []


def _list_pending_author_notes() -> list:
    try:
        from author_notes import AuthorNoteStore
        return AuthorNoteStore(AUTHOR_NOTES_FILE).list_pending()
    except Exception:
        return []


def _reject_news_draft(draft_id: str) -> bool:
    try:
        from news.drafts import DraftStore
        store = DraftStore(NEWS_DRAFTS_FILE)
        d = store.get(draft_id)
        if not d or d.status not in ("pending_review", "revised"):
            return False
        d.status = "rejected"
        store.update(d)
        return True
    except Exception:
        return False


def _reject_author_note_draft(draft_id: str) -> bool:
    try:
        from author_notes import AuthorNoteStore
        store = AuthorNoteStore(AUTHOR_NOTES_FILE)
        d = store.get(draft_id)
        if not d or d.status not in ("pending_review", "revised"):
            return False
        d.status = "rejected"
        store.update(d)
        return True
    except Exception:
        return False


def _purge_older_than(days: int) -> dict:
    """Reject все pending драфты старше N дней. Возвращает счётчики."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=max(1, days))
    n_news = 0
    n_notes = 0
    try:
        from news.drafts import DraftStore
        store = DraftStore(NEWS_DRAFTS_FILE)
        for d in store.list_pending():
            try:
                ts = datetime.fromisoformat(d.created_at.replace("Z", "+00:00"))
            except Exception:
                continue
            if ts < cutoff:
                d.status = "rejected"
                store.update(d)
                n_news += 1
    except Exception:
        pass
    try:
        from author_notes import AuthorNoteStore
        store = AuthorNoteStore(AUTHOR_NOTES_FILE)
        for d in store.list_pending():
            try:
                ts = datetime.fromisoformat(d.created_at.replace("Z", "+00:00"))
            except Exception:
                continue
            if ts < cutoff:
                d.status = "rejected"
                store.update(d)
                n_notes += 1
    except Exception:
        pass
    return {"news": n_news, "author_notes": n_notes}


def _render_news_row(d) -> str:
    sn = d.source_news or {}
    cj = d.claude_json or {}
    title = html_lib.escape((cj.get("specific_title") or sn.get("title") or "(без заголовка)")[:120])
    source = html_lib.escape((sn.get("source") or "")[:30])
    sector = html_lib.escape((sn.get("sector") or "")[:20])
    impact = sn.get("impact_score") or 0
    created = html_lib.escape((d.created_at or "")[:16].replace("T", " "))
    did = html_lib.escape(d.draft_id, quote=True)
    return (
        f'<tr>'
        f'<td>{created}</td>'
        f'<td>{source}</td>'
        f'<td>{sector}</td>'
        f'<td>{int(impact)}</td>'
        f'<td style="text-align:left">{title}</td>'
        f'<td><button type="button" onclick="rejectNews(\'{did}\')">❌</button></td>'
        f'</tr>'
    )


def _render_note_row(d) -> str:
    cj = d.claude_json or {}
    rubric = html_lib.escape((d.rubric or "")[:30])
    preview = html_lib.escape((cj.get("body") or cj.get("text") or "")[:100])
    created = html_lib.escape((d.created_at or "")[:16].replace("T", " "))
    did = html_lib.escape(d.draft_id, quote=True)
    return (
        f'<tr>'
        f'<td>{created}</td>'
        f'<td>{rubric}</td>'
        f'<td style="text-align:left">{preview}</td>'
        f'<td><button type="button" onclick="rejectNote(\'{did}\')">❌</button></td>'
        f'</tr>'
    )


@app.get("/admin/queue", response_class=HTMLResponse)
async def queue_page(request: Request, auth=Depends(authenticate)):
    news_pending = _list_pending_news()
    notes_pending = _list_pending_author_notes()
    csrf_token = request.cookies.get(CSRF_COOKIE) or _new_csrf_token()

    news_pending_sorted = sorted(
        news_pending,
        key=lambda d: float((d.source_news or {}).get("impact_score") or 0),
        reverse=True,
    )
    notes_pending_sorted = sorted(notes_pending, key=lambda d: d.created_at or "", reverse=True)

    news_rows = "".join(_render_news_row(d) for d in news_pending_sorted) or (
        '<tr><td colspan="6" style="text-align:center; color:#888">Нет pending news</td></tr>'
    )
    notes_rows = "".join(_render_note_row(d) for d in notes_pending_sorted) or (
        '<tr><td colspan="4" style="text-align:center; color:#888">Нет pending author notes</td></tr>'
    )

    page = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Очередь черновиков — AI Наставник</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
    body {{ font-family: 'Segoe UI', sans-serif; margin: 2em; background: #1a1a2e; color: #eee; }}
    .container {{ max-width: 1200px; margin: auto; }}
    .card {{ background: #16213e; padding: 1em; border-radius: 8px; margin-bottom: 1em; }}
    button {{ background: #e94560; color: white; border: none; padding: 0.4em 0.8em; border-radius: 5px; cursor: pointer; }}
    button.danger {{ background: #b00020; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 0.92em; }}
    th, td {{ border: 1px solid #2a3a5e; padding: 6px; text-align: center; }}
    th {{ background: #0f3460; }}
    input[type=number] {{ width: 4em; padding: 0.3em; background: #0f3460; color: #eee; border: 1px solid #2a3a5e; }}
    .toolbar {{ display: flex; gap: 0.5em; align-items: center; }}
    a {{ color: #e94560; }}
</style>
</head>
<body>
<div class="container">
    <p><a href="/admin">← Назад к дашборду</a></p>
    <h1>📥 Очередь черновиков</h1>
    <input type="hidden" name="csrf_token" value="{csrf_token}">

    <div class="card">
        <h3>🧹 Массовая чистка</h3>
        <div class="toolbar">
            <label>Reject pending старше</label>
            <input type="number" id="purgeDays" value="3" min="1" max="365">
            <label>дней</label>
            <button type="button" class="danger" onclick="purgeOld()">Запустить</button>
        </div>
        <div id="purgeMsg" style="margin-top: 0.7em;"></div>
    </div>

    <div class="card">
        <h3>📰 News pending ({len(news_pending)})</h3>
        <table>
            <tr><th>Created</th><th>Source</th><th>Sector</th><th>Impact</th><th>Title</th><th></th></tr>
            {news_rows}
        </table>
    </div>

    <div class="card">
        <h3>✍️ Author notes pending ({len(notes_pending)})</h3>
        <table>
            <tr><th>Created</th><th>Rubric</th><th>Preview</th><th></th></tr>
            {notes_rows}
        </table>
    </div>
</div>
<script>
    var CSRF = "{csrf_token}";

    async function _post(url, body) {{
        var form = new FormData();
        form.append("csrf_token", CSRF);
        for (var k in body) form.append(k, body[k]);
        var r = await fetch(url, {{ method: "POST", body: form }});
        return r.json();
    }}

    async function rejectNews(did) {{
        var r = await _post("/admin/queue/reject", {{ kind: "news", draft_id: did }});
        if (r.status === "ok") location.reload(); else alert("Ошибка: " + r.detail);
    }}

    async function rejectNote(did) {{
        var r = await _post("/admin/queue/reject", {{ kind: "author_note", draft_id: did }});
        if (r.status === "ok") location.reload(); else alert("Ошибка: " + r.detail);
    }}

    async function purgeOld() {{
        var days = document.getElementById("purgeDays").value;
        if (!confirm("Reject все pending старше " + days + " дней?")) return;
        var r = await _post("/admin/queue/purge_older_than", {{ days: days }});
        var msg = document.getElementById("purgeMsg");
        if (r.status === "ok") {{
            msg.textContent = "✅ Reject: news=" + r.news + ", author_notes=" + r.author_notes;
            setTimeout(function() {{ location.reload(); }}, 1500);
        }} else {{
            msg.textContent = "❌ " + r.detail;
        }}
    }}
</script>
</body>
</html>"""
    response = HTMLResponse(content=page)
    response.set_cookie(
        CSRF_COOKIE, csrf_token,
        httponly=False, samesite="strict", max_age=3600,
    )
    return response


@app.post("/admin/queue/reject")
async def queue_reject(
    request: Request,
    kind: str = Form(...),
    draft_id: str = Form(...),
    csrf_token: str = Form(""),
    auth=Depends(authenticate),
):
    _verify_csrf(request, csrf_token)
    if kind == "news":
        ok = _reject_news_draft(draft_id)
    elif kind == "author_note":
        ok = _reject_author_note_draft(draft_id)
    else:
        return {"status": "error", "detail": f"unknown kind: {kind}"}
    if not ok:
        return {"status": "error", "detail": "draft not found or not pending"}
    return {"status": "ok", "detail": f"{kind} rejected"}


@app.post("/admin/queue/purge_older_than")
async def queue_purge(
    request: Request,
    days: int = Form(...),
    csrf_token: str = Form(""),
    auth=Depends(authenticate),
):
    _verify_csrf(request, csrf_token)
    if days < 1 or days > 365:
        return {"status": "error", "detail": "days must be 1..365"}
    res = _purge_older_than(days)
    return {"status": "ok", "news": res["news"], "author_notes": res["author_notes"]}


if __name__ == "__main__":
    import uvicorn

    _ensure_password_set()
    public = os.getenv("ADMIN_BIND_PUBLIC", "false").strip().lower() in ("1", "true", "yes")
    host = "0.0.0.0" if public else "127.0.0.1"
    uvicorn.run(app, host=host, port=8000, log_level="info")
