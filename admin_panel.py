import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from aiogram import Bot
from core.safety import Sentinel

app = FastAPI(title="TG-Novice AI Control Panel")

# ----------------- Шаблоны -----------------
templates = Jinja2Templates(directory="admin_templates")

# Глобальные переменные (проставятся при инициализации)
bot: Optional[Bot] = None
sentinel: Optional[Sentinel] = None
channel_id: Optional[int] = None
owner_id: Optional[int] = None
stats_file = Path("post_stats.json")

# ----------------- Статистика (простая JSON-база) -----------------
def load_stats():
    if stats_file.exists():
        with open(stats_file, "r") as f:
            return json.load(f)
    return {"market": 0, "news": 0, "education": 0, "total": 0}

def save_stats(stats):
    with open(stats_file, "w") as f:
        json.dump(stats, f)

# ----------------- Ручки -----------------
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    stats = load_stats()
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "stats": stats,
            "channel_id": channel_id,
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
    )

@app.post("/force_post")
async def force_post(post_type: str = Form(...), draft_text: str = Form("")):
    """
    Принудительно публикует пост заданного типа.
    Если передан draft_text — использует его, иначе генерирует через AI.
    """
    if not bot or not sentinel or not channel_id:
        return {"status": "error", "detail": "Bot not initialized"}

    try:
        # Если текст передан вручную, публикуем как есть
        if draft_text.strip():
            await bot.send_message(channel_id, draft_text)
            # Обновляем статистику
            stats = load_stats()
            stats[post_type] = stats.get(post_type, 0) + 1
            stats["total"] += 1
            save_stats(stats)
            return {"status": "ok", "detail": f"Posted custom {post_type} post"}

        # Иначе запускаем генерацию через Sentinel (ваш модуль должен иметь хендлеры)
        # Здесь можно вызвать соответствующую функцию из основного бота,
        # но поскольку у нас нет прямого доступа, шлём специальное событие.
        # Для простоты: публикуем fallback-урок с пометкой "принудительная".
        await sentinel._publish_fallback()
        stats = load_stats()
        stats["education"] += 1
        stats["total"] += 1
        save_stats(stats)
        return {"status": "ok", "detail": "Published fallback education post"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

# ----------------- Запуск сервера в отдельном потоке -----------------
def run_admin_server(host: str = "127.0.0.1", port: int = 8000):
    uvicorn.run(app, host=host, port=port, log_level="info")