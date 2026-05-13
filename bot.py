"""
Депозит под надзором ИИ — Telegram bot (one-file MVP).

Режимы запуска:
    python bot.py              — фоновый процесс: scheduler (+ webhook если ENABLE_WEBHOOK=true)
    python bot.py --post-now   — опубликовать один пост и выйти (для ручной проверки)

Все ключи и флаги — в .env (см. env.example).
"""

from __future__ import annotations

import admin_panel
import os
import sys
import json
import html
import base64
import random
import asyncio
import logging
import argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

from dotenv import load_dotenv

# ---- внешние клиенты подключаем здесь, тяжёлые (moviepy) — лениво
import ccxt
import pandas as pd
import mplfinance as mpf
import ta

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.types import (
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    CallbackQuery,
)


class _ThreadedResolverSession(AiohttpSession):
    """AiohttpSession с системным DNS (getaddrinfo) вместо aiodns.

    На Windows aiodns не всегда видит DNS-серверы, настроенные через DHCP,
    и валится с 'Timeout while contacting DNS servers'. ThreadedResolver
    использует системный getaddrinfo — надёжнее, чуть медленнее.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._connector_init["resolver"] = aiohttp.ThreadedResolver()

from anthropic import Anthropic
from openai import OpenAI

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from fastapi import FastAPI, Request, HTTPException
import uvicorn

from core.safety import Sentinel
from core.styleguard import StyleGuard
from core.mistake_tracker import MistakeTracker
from core.json_store import load_json, save_json, update_json
from core.publish_lock import try_claim_for_publishing, release_claim
from core.telegram_send import split_html_for_telegram
from core.content_mix import (
    CATEGORY_MAP as _CM_CATEGORY_MAP,
    CONTENT_MIX_CHANNEL_MODE_MIN as _CM_CHANNEL_MODE_MIN,
    CONTENT_MIX_FALLBACK_RECOMMEND as _CM_FALLBACK,
    CONTENT_MIX_LOG_CAP as _CM_LOG_CAP,
    CONTENT_MIX_LOW_DATA_THRESHOLD as _CM_LOW_DATA,
    CONTENT_MIX_OVERREP_DELTA as _CM_OVER_DELTA,
    CONTENT_MIX_TARGET as _CM_TARGET,
    CONTENT_MIX_UNDERREP_DELTA as _CM_UNDER_DELTA,
    CONTENT_MIX_WINDOW_DAYS as _CM_WINDOW_DAYS,
    category_for as _cm_category_for,
    compute_mix as _cm_compute_mix,
)
from core.content_mix_writer import (
    append_event as _cmw_append_event,
    make_event as _cmw_make_event,
    migrate_state as _cmw_migrate_state,
)
styleguard: Optional[StyleGuard] = None
mistake_tracker: Optional[MistakeTracker] = None
# =============================================================================
# CONFIG
# =============================================================================

ROOT = Path(__file__).resolve().parent
load_dotenv(dotenv_path=ROOT / ".env")

STATE_FILE = ROOT / "state.json"
HISTORY_FILE = ROOT / "history.json"
PAPER_TRADES_FILE = ROOT / "paper_trades.json"
TRADE_JOURNAL_FILE = ROOT / "trade_journal.json"
NEWS_CACHE_FILE = ROOT / "news_cache.json"
NEWS_HISTORY_FILE = ROOT / "news_history.json"
NEWS_DRAFTS_FILE = ROOT / "news_drafts.json"
# Stage 10
AUTHOR_NOTES_FILE = ROOT / "author_notes_drafts.json"
# Stage 13 — weekly diary
WEEKLY_DIARY_FILE = ROOT / "weekly_diary_drafts.json"
# Stage 8a — confirm/live storage
CONFIRM_TRADES_FILE = ROOT / "confirm_trades.json"
LIVE_TRADES_FILE = ROOT / "live_trades.json"
LIVE_TRADE_JOURNAL_FILE = ROOT / "live_trade_journal.json"
OUTPUTS = ROOT / "outputs"
CHARTS_DIR = OUTPUTS / "charts"
IMAGES_DIR = OUTPUTS / "images"
NEWS_IMAGES_DIR = OUTPUTS / "news_images"           # Stage 12b — кэш AI-картинок по news_hash
NEWS_SOURCE_IMAGES_DIR = OUTPUTS / "news_source_images"  # Stage 12e — кэш og:image / twitter:image из источника
VIDEOS_DIR = OUTPUTS / "videos"
for d in (OUTPUTS, CHARTS_DIR, IMAGES_DIR, NEWS_IMAGES_DIR, NEWS_SOURCE_IMAGES_DIR, VIDEOS_DIR):
    d.mkdir(parents=True, exist_ok=True)


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
CHANNEL_ID     = os.getenv("CHANNEL_ID", "").strip()
OWNER_CHAT_ID  = os.getenv("OWNER_CHAT_ID", "").strip()

CLAUDE_API_KEY       = os.getenv("CLAUDE_API_KEY", "").strip()
CLAUDE_MODEL         = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6").strip()
OPENAI_API_KEY       = os.getenv("OPENAI_API_KEY", "").strip()
IMAGE_MODEL          = os.getenv("IMAGE_MODEL", "gpt-image-2").strip()
IMAGE_MODEL_FALLBACK = os.getenv("IMAGE_MODEL_FALLBACK", "gpt-image-1").strip()

PARTNER_URL = os.getenv("PARTNER_URL", "").strip()

DRY_RUN         = _env_bool("DRY_RUN", True)
GENERATE_IMAGES = _env_bool("GENERATE_IMAGES", False)
GENERATE_VIDEO  = _env_bool("GENERATE_VIDEO", False)

ENABLE_WEBHOOK  = _env_bool("ENABLE_WEBHOOK", False)
WEBHOOK_SECRET  = os.getenv("WEBHOOK_SECRET", "").strip()
WEBHOOK_HOST    = os.getenv("WEBHOOK_HOST", "0.0.0.0").strip()
WEBHOOK_PORT    = _env_int("WEBHOOK_PORT", 8000)

FLASH_THRESHOLD  = _env_float("FLASH_THRESHOLD", 10.0)
PARTNER_EVERY_N  = _env_int("PARTNER_EVERY_N", 4)
QUESTION_EVERY_N = _env_int("QUESTION_EVERY_N", 3)
IMAGE_EVERY_N    = _env_int("IMAGE_EVERY_N", 4)
HISTORY_LIMIT    = _env_int("HISTORY_LIMIT", 5)

SCHEDULER_TZ       = os.getenv("SCHEDULER_TZ", "Europe/Moscow").strip()
POST_MORNING_HOUR  = _env_int("POST_MORNING_HOUR", 10)
POST_EVENING_HOUR  = _env_int("POST_EVENING_HOUR", 19)

# Если канал не задан, насильно в DRY_RUN, чтобы не уронить публикацию.
if not CHANNEL_ID and not DRY_RUN:
    DRY_RUN = True

DISCLAIMER = (
    "Не является финансовым советом. Это личный дневник обучения, "
    "а AI-анализ носит ознакомительный характер."
)
# Stage 9: короткий дисклеймер для обычных постов (длинный — только в закрепе и больших гайдах).
DISCLAIMER_SHORT = "Не финсовет. Это дневник обучения и AI-разбор."

FALLBACK_TOPICS = [
    "риск-менеджмент: почему 95% новичков сливают в первые месяцы",
    "FOMO: как распознать момент, когда тебе срочно «нужно» зайти",
    "плечо: что на самом деле делает x10 с твоим депозитом",
    "ликвидация: математика, которую новичок обычно не считает",
    "стоп-лосс: почему без него любая стратегия рано или поздно ломается",
    "психология новичка: эмоциональные циклы страх–жадность",
]

PARTNER_HOOKS = [
    'Графики и сделки разбираю через биржу, где сам учусь: <a href="{url}">площадка</a>',
    'Я тестирую инструменты здесь: <a href="{url}">площадка</a>',
    'Где смотрю фандинг и OHLCV: <a href="{url}">площадка</a>',
]

BRAND = "Депозит под надзором ИИ"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger("bot")

# File-логирование: pythonw.exe не имеет stdout/stderr, поэтому без файлового
# хендлера логи Task Scheduler-инстанса теряются. Пишем в outputs/scheduler.log
# с ротацией (5 файлов по 2 MB).
try:
    from logging.handlers import RotatingFileHandler
    from core.log_redact import RedactFilter
    _log_file = OUTPUTS / "scheduler.log"
    _file_handler = RotatingFileHandler(
        str(_log_file), maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    _file_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s — %(message)s"
    ))
    # Этап 1.7: redact-фильтр на root-уровне — покрывает все handlers.
    _redact = RedactFilter()
    logging.getLogger().addFilter(_redact)
    for _h in logging.getLogger().handlers:
        _h.addFilter(_redact)
    logging.getLogger().addHandler(_file_handler)
    _file_handler.addFilter(_redact)
    log.info("file logging → %s", _log_file)
except Exception as _e:  # pragma: no cover — лог-файл не должен блокировать запуск
    log.warning("file logging setup failed: %s", _e)

# =============================================================================
# STATE & HISTORY
# =============================================================================

_STATE_DEFAULT = {"post_count": 0, "last_image_at": 0, "last_partner_at": 0}


def load_state() -> dict:
    return load_json(STATE_FILE, default=dict(_STATE_DEFAULT), expected_type=dict)


def save_state(state: dict) -> None:
    save_json(STATE_FILE, state)


def load_history() -> list:
    return load_json(HISTORY_FILE, default=[], expected_type=list)


# =============================================================================
# CONTENT MIX TRACKER (Stage 10+)
# =============================================================================
# Целевой микс на 7 дней (только по 5 целевым категориям, "other" не учитывается):
#   market_chart=40 · education=20 · news=15 · author_note=15 · trade_diary=10.
#
# state.content_mix_log — rolling список событий со схемой:
#   {timestamp, post_type, category, published_to (owner|channel), title, source}.
# Owner-preview и channel-публикация — это ДВА разных события.
# Для рекомендации:
#   - если за 7 дней >=3 channel-событий → используем только channel
#   - иначе → используем все события (owner+channel) — чтобы статистика не была пустой
#     в DRY_RUN/preview-режиме.

# Этап 2.2: константы и CATEGORY_MAP теперь в core/content_mix.py — алиасы
# для существующего кода bot.py (compute_content_mix, _content_mix_hint_block).
CONTENT_MIX_TARGET = _CM_TARGET
CONTENT_MIX_WINDOW_DAYS = _CM_WINDOW_DAYS
CONTENT_MIX_LOG_CAP = _CM_LOG_CAP
CONTENT_MIX_OVERREP_DELTA = _CM_OVER_DELTA
CONTENT_MIX_UNDERREP_DELTA = _CM_UNDER_DELTA
CONTENT_MIX_CHANNEL_MODE_MIN = _CM_CHANNEL_MODE_MIN
CONTENT_MIX_LOW_DATA_THRESHOLD = _CM_LOW_DATA
CONTENT_MIX_FALLBACK_RECOMMEND = _CM_FALLBACK
CATEGORY_MAP = _CM_CATEGORY_MAP

_category_for = _cm_category_for


def _migrate_content_mix_state_if_needed(s: dict) -> bool:
    """Backwards-compat обёртка над core.content_mix_writer.migrate_state."""
    return _cmw_migrate_state(s)


def _log_post_event(
    post_type: str,
    *,
    published_to: str,
    title: str = "",
    source: str = "",
) -> None:
    """Записать событие публикации (owner-preview или channel-publish).

    post_type — сырой тип (market / flash / news / scam_radar / author_note / trade ...).
    published_to — 'owner' | 'channel'.
    """
    if published_to not in ("owner", "channel"):
        log.warning("content_mix: bad published_to=%r, skip", published_to)
        return
    s = load_state()
    event = _cmw_make_event(
        post_type, published_to=published_to, title=title, source=source,
    )
    _cmw_append_event(s, event)
    save_state(s)


def compute_content_mix() -> dict:
    """7-дневная статистика. Делегирует в core.content_mix.compute_mix."""
    s = load_state()
    _migrate_content_mix_state_if_needed(s)
    save_state(s)
    return _cm_compute_mix(s.get("content_mix_log") or [])


def _content_mix_hint_block(*, allow: bool = True) -> str | None:
    """Готовый текстовый блок для Claude context (см. ТЗ §7).
    None если allow=False (например, flash) или данных совсем нет."""
    if not allow:
        return None
    res = compute_content_mix()
    if res["total_posts"] == 0:
        return None
    pct = lambda c: int(round(res["shares"].get(c, 0.0) * 100))
    tgt = lambda c: int(round(res["target"].get(c, 0.0) * 100))
    over = res.get("overrepresented") or []
    over_text = (" Не делай очередной пост из overrepresented категории: "
                 + ", ".join(over) + ".") if over else ""
    lines = [
        f"Content mix last 7 days (mode={res['mode']}, total={res['total_posts']}):",
        f"  market_chart: {pct('market_chart')}% (цель {tgt('market_chart')}%)",
        f"  education:    {pct('education')}% (цель {tgt('education')}%)",
        f"  news:         {pct('news')}% (цель {tgt('news')}%)",
        f"  author_note:  {pct('author_note')}% (цель {tgt('author_note')}%)",
        f"  trade_diary:  {pct('trade_diary')}% (цель {tgt('trade_diary')}%)",
        "",
        f"Recommended next content type: {res['recommended']}",
        f"Reason: {res['reason']}",
        "",
        ("Instruction: Если нет срочного события (flash, news impact>=90, closed trade with strong "
         "lesson, high-risk scam alert), сделай уклон в recommended_type." + over_text),
    ]
    return "\n".join(lines)


def append_history(entry: dict, limit: int = HISTORY_LIMIT) -> None:
    def _mut(history: list) -> list:
        history.append(entry)
        return history[-limit:]

    update_json(HISTORY_FILE, default=[], expected_type=list, mutator=_mut)


# =============================================================================
# MARKET
# =============================================================================

class Market:
    def __init__(self, spot_symbol: str = "BTC/USDT", swap_symbol: str = "BTC/USDT:USDT"):
        self.spot_symbol = spot_symbol
        self.swap_symbol = swap_symbol
        self.ex = ccxt.gateio({"enableRateLimit": True})

    def ticker(self) -> dict | None:
        try:
            t = self.ex.fetch_ticker(self.spot_symbol)
            return {
                "symbol": self.spot_symbol,
                "price": t.get("last"),
                "change_24h": t.get("percentage"),
                "high_24h": t.get("high"),
                "low_24h": t.get("low"),
            }
        except Exception as e:
            log.warning("ticker недоступен: %s", e)
            return None

    def ohlcv(self, timeframe: str = "1h", limit: int = 300):
        try:
            raw = self.ex.fetch_ohlcv(self.spot_symbol, timeframe, limit=limit)
            df = pd.DataFrame(raw, columns=["ts", "Open", "High", "Low", "Close", "Volume"])
            df["ts"] = pd.to_datetime(df["ts"], unit="ms")
            df.set_index("ts", inplace=True)
            return df
        except Exception as e:
            log.warning("OHLCV недоступен: %s", e)
            return None

    @staticmethod
    def indicators(df):
        if df is None or len(df) < 20:
            return df
        df = df.copy()
        if len(df) >= 50:
            df["ema50"] = ta.trend.ema_indicator(df["Close"], 50)
        if len(df) >= 200:
            df["ema200"] = ta.trend.ema_indicator(df["Close"], 200)
        df["rsi"] = ta.momentum.rsi(df["Close"], 14)
        return df

    @staticmethod
    def volume_spike(df) -> bool:
        if df is None or len(df) < 20:
            return False
        last = df["Volume"].iloc[-1]
        avg = df["Volume"].rolling(20).mean().iloc[-1]
        if pd.isna(last) or pd.isna(avg) or avg == 0:
            return False
        return bool(last > avg * 2)

    def funding(self) -> float | None:
        try:
            if not self.ex.has.get("fetchFundingRate"):
                return None
            data = self.ex.fetch_funding_rate(self.swap_symbol)
            return data.get("fundingRate")
        except Exception as e:
            log.debug("funding недоступен: %s", e)
            return None

    def open_interest(self) -> float | None:
        try:
            if not self.ex.has.get("fetchOpenInterest"):
                return None
            data = self.ex.fetch_open_interest(self.swap_symbol)
            return data.get("openInterestAmount") or data.get("openInterestValue")
        except Exception as e:
            log.debug("OI недоступен: %s", e)
            return None


# =============================================================================
# CHART
# =============================================================================

def make_chart(df, out_path: Path) -> Path | None:
    """Fallback-рендерер через mplfinance. Используется, если Playwright/Chromium недоступны."""
    try:
        tail = df.tail(120).copy()
        plots = []
        if "ema50" in tail.columns and tail["ema50"].notna().any():
            plots.append(mpf.make_addplot(tail["ema50"], color="#b7791f", width=1.0))
        if "ema200" in tail.columns and tail["ema200"].notna().any():
            plots.append(mpf.make_addplot(tail["ema200"], color="#744210", width=1.0))

        style = mpf.make_mpf_style(base_mpf_style="charles", rc={"font.size": 9})
        mpf.plot(
            tail,
            type="candle",
            addplot=plots or None,
            volume=True,
            style=style,
            savefig=dict(fname=str(out_path), dpi=120, bbox_inches="tight"),
        )
        return out_path
    except Exception as e:
        log.warning("chart failed: %s", e)
        return None


# --- TradingView-style (Lightweight Charts + headless Chromium) ---
# Установка: pip install playwright && python -m playwright install chromium
# Это НАШ график на НАШИХ данных Gate.io: ни логина в TV, ни cookies, ни скрейпа,
# ни чужих watermark — только public OSS-библиотека lightweight-charts через CDN.

_TV_CHART_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>chart</title>
<style>
  html, body { margin:0; padding:0; background:#0f0f12;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; }
  #container { width: 1280px; height: 720px; position: relative; overflow: hidden; }
  #chart { width: 100%; height: 100%; }
  #watermark {
    position: absolute; top: 24px; left: 36px; z-index: 10;
    color: rgba(255,255,255,0.07); font-size: 54px; font-weight: 800;
    letter-spacing: 1px; pointer-events: none; user-select: none;
  }
  #brand {
    position: absolute; bottom: 10px; right: 16px; z-index: 10;
    color: rgba(200,200,210,0.55); font-size: 12px; letter-spacing: 0.3px;
  }
  #meta {
    position: absolute; top: 16px; right: 20px; z-index: 10;
    color: rgba(200,200,210,0.85); font-size: 13px; text-align: right;
    font-variant-numeric: tabular-nums;
  }
  #meta b { color:#e8e8ec; font-size: 15px; }
</style>
</head>
<body>
<div id="container">
  <div id="watermark">__BRAND__</div>
  <div id="meta">__META_HTML__</div>
  <div id="brand">BTC/USDT · 1h · Gate.io · lightweight-charts</div>
  <div id="chart"></div>
</div>
<script src="https://unpkg.com/lightweight-charts@4.2.2/dist/lightweight-charts.standalone.production.js"></script>
<script>
(function(){
  const CANDLES = __CANDLES__;
  const EMA50   = __EMA50__;
  const EMA200  = __EMA200__;
  const VOLUMES = __VOLUMES__;
  const RSI     = __RSI__;
  const LEVELS  = __LEVELS__;

  const chart = LightweightCharts.createChart(document.getElementById('chart'), {
    layout: { background: { color: '#0f0f12' }, textColor: '#c8c8d0' },
    grid:   { vertLines: { color: '#1b1b22' }, horzLines: { color: '#1b1b22' } },
    timeScale: { timeVisible: true, secondsVisible: false, borderColor: '#2a2a33' },
    rightPriceScale: { borderColor: '#2a2a33', scaleMargins: { top: 0.08, bottom: 0.32 } },
    crosshair: { mode: 0 },
    width: 1280, height: 720,
  });

  const candleSeries = chart.addCandlestickSeries({
    upColor:'#2e8f5a', downColor:'#b04343',
    borderUpColor:'#2e8f5a', borderDownColor:'#b04343',
    wickUpColor:'#2e8f5a', wickDownColor:'#b04343',
  });
  candleSeries.setData(CANDLES);

  if (EMA50.length) {
    const s = chart.addLineSeries({ color:'#b7791f', lineWidth:1,
      priceLineVisible:false, lastValueVisible:false });
    s.setData(EMA50);
  }
  if (EMA200.length) {
    const s = chart.addLineSeries({ color:'#c26a3a', lineWidth:1,
      priceLineVisible:false, lastValueVisible:false });
    s.setData(EMA200);
  }

  const volSeries = chart.addHistogramSeries({
    priceScaleId: '',
    priceFormat: { type: 'volume' },
  });
  volSeries.priceScale().applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } });
  volSeries.setData(VOLUMES);

  if (RSI.length) {
    const rsiSeries = chart.addLineSeries({
      color: '#8a7fd8', lineWidth: 1, priceScaleId: 'rsi',
      lastValueVisible: false, priceLineVisible: false,
    });
    rsiSeries.setData(RSI);
    chart.priceScale('rsi').applyOptions({
      scaleMargins: { top: 0.02, bottom: 0.86 }, borderColor: '#2a2a33',
    });
    // RSI 70 / 30 guides
    rsiSeries.createPriceLine({ price: 70, color: 'rgba(176,67,67,0.45)',
      lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: '' });
    rsiSeries.createPriceLine({ price: 30, color: 'rgba(46,143,90,0.45)',
      lineWidth: 1, lineStyle: 2, axisLabelVisible: false, title: '' });
  }

  LEVELS.forEach(function(lv){
    candleSeries.createPriceLine({
      price: lv.price,
      color: lv.kind === 'resistance' ? '#c76d6d' : '#6dbf91',
      lineWidth: 1, lineStyle: 2,
      axisLabelVisible: true, title: lv.label,
    });
  });

  chart.timeScale().fitContent();

  // даём движку дорисоваться до сигнала готовности
  requestAnimationFrame(function(){ requestAnimationFrame(function(){
    window.__ready = true;
    document.title = 'ready';
  }); });
})();
</script>
</body>
</html>
"""


def _sr_levels(df) -> list[dict]:
    """Простые уровни: глобальный диапазон 120 свечей + ближний диапазон 40 свечей."""
    if df is None or len(df) < 30:
        return []
    far = df.tail(120)
    near = df.tail(40)
    r_far = float(far["High"].max())
    s_far = float(far["Low"].min())
    r_near = float(near["High"].max())
    s_near = float(near["Low"].min())
    out = [
        {"price": r_far, "kind": "resistance", "label": f"R {r_far:,.0f}"},
        {"price": s_far, "kind": "support",    "label": f"S {s_far:,.0f}"},
    ]
    # ближние только если заметно отличаются
    if r_far > 0 and abs(r_near - r_far) / r_far > 0.004:
        out.append({"price": r_near, "kind": "resistance", "label": f"R' {r_near:,.0f}"})
    if s_far > 0 and abs(s_near - s_far) / s_far > 0.004:
        out.append({"price": s_near, "kind": "support", "label": f"S' {s_near:,.0f}"})
    return out


async def make_chart_tv(df, out_dir: Path) -> Path | None:
    """Рендерит TradingView-style график через Lightweight Charts + headless Chromium.

    Возвращает путь к PNG или None, если Playwright/Chromium недоступны либо упал рендер —
    в этом случае вызывающая сторона должна откатиться на `make_chart` (mplfinance).
    """
    try:
        from playwright.async_api import async_playwright  # type: ignore
    except ImportError:
        log.info("playwright не установлен — TV-chart пропущен, fallback на mplfinance")
        return None

    try:
        tail = df.tail(180).copy().reset_index()
        # datetime → UNIX seconds: через .timestamp(), т.к. на разных pandas
        # единицей datetime64 может быть ns / ms / us — astype("int64") даст разное.
        ts = [int(t.timestamp()) for t in tail["ts"]]

        candles = []
        volumes = []
        for i in range(len(tail)):
            o = float(tail["Open"].iloc[i]);  c = float(tail["Close"].iloc[i])
            h = float(tail["High"].iloc[i]);  l = float(tail["Low"].iloc[i])
            v = float(tail["Volume"].iloc[i])
            t = int(ts[i])
            candles.append({"time": t, "open": o, "high": h, "low": l, "close": c})
            volumes.append({
                "time": t, "value": v,
                "color": "rgba(46,143,90,0.55)" if c >= o else "rgba(176,67,67,0.55)",
            })

        def _line(col: str) -> list[dict]:
            if col not in tail.columns:
                return []
            pts: list[dict] = []
            for i in range(len(tail)):
                v = tail[col].iloc[i]
                if pd.notna(v):
                    pts.append({"time": int(ts[i]), "value": float(v)})
            return pts

        ema50 = _line("ema50")
        ema200 = _line("ema200")
        rsi = _line("rsi")
        levels = _sr_levels(df)

        last_close = float(tail["Close"].iloc[-1])
        last_rsi = float(tail["rsi"].iloc[-1]) if "rsi" in tail.columns and pd.notna(tail["rsi"].iloc[-1]) else None
        meta_parts = [f"<b>{last_close:,.2f}</b>"]
        if last_rsi is not None:
            meta_parts.append(f"RSI {last_rsi:.1f}")
        meta_html = " · ".join(meta_parts)

        out_dir.mkdir(parents=True, exist_ok=True)
        html_path = out_dir / "chart.html"
        png_path = out_dir / "chart.png"

        # ASCII-watermark — кириллический BRAND ломается в headless Chromium
        # без подгруженного Cyrillic-фолбэка. Используем handle канала (@ai_deposit_diary
        # или то, что в CHANNEL_ID), он гарантированно отрисуется любым шрифтом.
        chart_watermark = CHANNEL_ID if CHANNEL_ID else "AI Deposit Diary"
        html_content = (
            _TV_CHART_HTML
            .replace("__BRAND__", chart_watermark)
            .replace("__META_HTML__", meta_html)
            .replace("__CANDLES__", json.dumps(candles))
            .replace("__EMA50__", json.dumps(ema50))
            .replace("__EMA200__", json.dumps(ema200))
            .replace("__VOLUMES__", json.dumps(volumes))
            .replace("__RSI__", json.dumps(rsi))
            .replace("__LEVELS__", json.dumps(levels))
        )
        html_path.write_text(html_content, encoding="utf-8")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                ctx = await browser.new_context(
                    viewport={"width": 1280, "height": 720},
                    device_scale_factor=2,
                )
                page = await ctx.new_page()
                await page.goto(html_path.resolve().as_uri())
                await page.wait_for_function("window.__ready === true", timeout=10_000)
                await page.wait_for_timeout(300)
                await page.locator("#container").screenshot(path=str(png_path))
            finally:
                await browser.close()

        return png_path
    except Exception as e:
        log.warning("TV-chart failed: %s", e)
        return None


# =============================================================================
# AI (Claude JSON + image)
# =============================================================================

CLAUDE_SYSTEM = f"""
Ты пишешь посты для Telegram-канала «{BRAND}» — это живой дневник новичка-трейдера,
которого AI-наставник каждый день ловит за руку, чтобы он не делал глупостей.

Канал — НЕ аналитический отчёт, НЕ крипто-гуру, НЕ сигнал-канал, НЕ мем-паблик.
Канал — мини-сцена: новичок смотрит на рынок/новость, хочет сделать что-то, внутренний
хомяк подталкивает, AI-наставник спокойно объясняет, почему так — опасно.

ТОН:
- живой, короткий, дневниковый
- эмоция новичка должна быть видна
- лёгкий юмор и умеренный сарказм допустимы
- БЕЗ токсичности, БЕЗ унижения аудитории, БЕЗ шуток над потерями людей
- БЕЗ «гуру», ракет, быков, x10/x20, «туземун», «залетаем», «иксы»

ЗАПРЕЩЕНО:
- сигналы, конкретные точки входа, гарантии прибыли
- «точно вырастет/упадёт», «инсайд», «киты точно покупают»
- фразы вида «я купил/я продал/меня ликвиднуло» (если не передан user_action)
- выдумывать цифры, если их нет в market_snapshot
- начинать пост с сухих штампов: «BTC торгуется на уровне», «Сегодня рассмотрим»,
  «Риск-менеджмент — это», «В данном посте», «Важно понимать, что»,
  «Данный анализ показывает»
- markdown-обёртка ```json``` или комментарии вне JSON

НАЧИНАЙ с человеческой реакции. Примеры хуков:
- «Смотрю на график и руки уже тянутся к кнопке.»
- «Цена дёрнулась, и внутренний хомяк проснулся.»
- «Кажется, рынок снова проверяет моё терпение.»
- «Новость громкая, но мозг уже пытается превратить её в сделку.»
- «Вот момент, где новичок обычно делает глупость.»

Режим работы задаётся полем mode:
- normal — обычный рыночный/наблюдательный пост по market_snapshot
- flash  — экстренный разбор сильного движения (|change_24h| >= порог);
           объяснить панику/эйфорию, без призыва к действию
- fallback_education — рыночные данные недоступны; пишем по теме market_snapshot.fallback_topic
                       БЕЗ конкретных цифр и цен

ДЛИНА (важно — Telegram caption-лимит фото 1024 символа, всё должно влезть в одно сообщение photo+caption):
- обычный/новостной/flash пост: 700–880 символов СУММАРНО по полям
  human_part + hamster_part + mentor_part + beginner_mistake + lesson + question
  (партнёрка и хэштеги добавляются автоматически уже после).
- обучающий (fallback_education): 700–900 символов суммарно — те же поля.
- абзац максимум 1–3 строки. Без длинных стен текста.
- mentor_part: 2–3 КОРОТКИХ абзаца, не больше. Каждая мысль ≤2 фраз.

СТРУКТУРА (мини-сцена):
1) human_part — живой хук + что увидел/почувствовал новичок (2–4 короткие фразы)
2) hamster_part — короткая эмоциональная реакция «внутреннего хомяка» в кавычках
                  (используй ~50% постов; null если не уместно — например, в обучающем без эмоций)
3) mentor_part — AI-наставник спокойно, строго и слегка саркастично возвращает на землю
                 (2–3 коротких абзаца — по смыслу; не больше)
4) beginner_mistake — ОДНА конкретная ошибка новичка, которую этот пост предотвращает (1 фраза)
5) lesson — короткий вывод 1–2 предложения, без призыва к действию

Если need_question=true — добавь поле question (один короткий вопрос аудитории).
Если нет — question=null.

Примеры реплик AI-наставника (для калибровки тона):
- «Зелёная свеча — это не торговый план.»
- «Если стопа нет, это не трейд, а надежда.»
- «Громкость новости не равна качеству входа.»
- «Сначала риск. Потом мечты.»
- «Ты не нашёл сделку. Ты нашёл оправдание нажать кнопку.»

Верни СТРОГО валидный JSON без markdown-обёртки и без комментариев:
{{
  "human_part": "...",
  "hamster_part": "... или null",
  "mentor_part": "...",
  "beginner_mistake": "...",
  "lesson": "...",
  "question": "... или null",
  "hashtags": ["#BTC", "#честный_путь"],
  "image_prompt": "короткий англоязычный prompt для gpt-image ИЛИ null",
  "should_generate_image": true,
  "short_summary": "одна строка для памяти, 8–14 слов"
}}
""".strip()


def _build_post_system_prompt() -> str:
    """Stage 13: к статическому CLAUDE_SYSTEM подмешиваем external style guides
    (base + trade + instructions). Кэш в style_guides.py — перечитывает .md
    при изменении mtime."""
    try:
        from style_guides import compose_style_context
        suffix = compose_style_context("base", "trade", "instructions")
    except Exception as e:
        log.debug("style guides unavailable: %s", e)
        suffix = ""
    return CLAUDE_SYSTEM + (suffix or "")


def ask_claude(client: Anthropic, context: dict, need_question: bool, mode: str) -> dict:
    user_payload = json.dumps(
        {"mode": mode, "need_question": need_question, "context": context},
        ensure_ascii=False,
    )
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1400,
        system=_build_post_system_prompt(),
        messages=[{"role": "user", "content": user_payload}],
    )
    raw = (resp.content[0].text or "").strip()
    # защита: снять возможные code-fences
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        log.error("Claude вернул не-JSON: %s\n---\n%s", e, raw[:500])
        raise
    # мягкие дефолты — поддерживаем и новые поля Stage 9, и старые (обратная совместимость)
    data.setdefault("human_part", "")
    data.setdefault("hamster_part", None)
    data.setdefault("mentor_part", "")
    data.setdefault("beginner_mistake", "")
    data.setdefault("lesson", data.get("conclusion") or "")  # legacy: conclusion -> lesson
    data.setdefault("question", None)
    data.setdefault("hashtags", [])
    data.setdefault("image_prompt", None)
    data.setdefault("should_generate_image", False)
    data.setdefault("short_summary", "")
    return data


def generate_image(openai_client: OpenAI, prompt: str, out_path: Path) -> Path | None:
    models = [m for m in (IMAGE_MODEL, IMAGE_MODEL_FALLBACK) if m]
    last_err: Exception | None = None
    for model in models:
        try:
            r = openai_client.images.generate(model=model, prompt=prompt, size="1024x1024")
            d = r.data[0]
            b64 = getattr(d, "b64_json", None)
            url = getattr(d, "url", None)
            if b64:
                out_path.write_bytes(base64.b64decode(b64))
                return out_path
            if url:
                import urllib.request
                urllib.request.urlretrieve(url, str(out_path))
                return out_path
            last_err = RuntimeError("image response has neither b64_json nor url")
        except Exception as e:
            log.warning("image model %s не сработал: %s", model, e)
            last_err = e
    log.error("генерация картинки не удалась: %s", last_err)
    return None


# =============================================================================
# POST BUILDER
# =============================================================================

def esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=False)


def build_post_html(
    payload: dict,
    post_type: str,
    include_partner: bool,
    post_num: int,
) -> str:
    parts: list[str] = []

    human = esc(payload.get("human_part", "")).strip()
    hamster = esc(payload.get("hamster_part") or "").strip()
    mentor = esc(payload.get("mentor_part", "")).strip()
    mistake = esc(payload.get("beginner_mistake") or "").strip()
    lesson = esc(payload.get("lesson") or payload.get("conclusion") or "").strip()

    if human:
        parts.append(human)

    if hamster:
        parts.append("")
        parts.append("🐹 <b>Внутренний хомяк</b>")
        parts.append(hamster)

    if mentor:
        parts.append("")
        parts.append("🤖 <b>AI-наставник</b>")
        parts.append(mentor)

    if mistake:
        parts.append("")
        parts.append("⚠️ <b>Ошибка новичка</b>")
        parts.append(mistake)

    if lesson:
        parts.append("")
        parts.append("📌 <b>Вывод</b>")
        parts.append(lesson)

    q = payload.get("question")
    if q:
        parts.append("")
        parts.append("💬 " + esc(q))

    if include_partner and PARTNER_URL:
        hook = PARTNER_HOOKS[post_num % len(PARTNER_HOOKS)]
        parts.append("")
        parts.append(hook.format(url=esc(PARTNER_URL)))

    parts.append("")
    # Stage 9: короткий дисклеймер в обычных постах. Длинный — для закрепа/гайдов.
    disclaimer_text = DISCLAIMER if post_type == "fallback_education" else DISCLAIMER_SHORT
    parts.append("<i>" + esc(disclaimer_text) + "</i>")

    tags = payload.get("hashtags") or []
    tags = [t if str(t).startswith("#") else f"#{t}" for t in tags]
    system_tags: list[str] = ["#честный_путь"]
    # Хомяк появился — отметим рубрикой #не_будь_хомяком, иначе #ошибки_новичка
    if hamster:
        system_tags.append("#не_будь_хомяком")
    else:
        system_tags.append("#ошибки_новичка")
    if post_type == "flash":
        system_tags.append("#flash")
    elif post_type == "fallback_education":
        system_tags.append("#термин_без_боли")
    all_tags = list(dict.fromkeys(tags + system_tags))  # dedupe, preserve order
    parts.append("")
    parts.append(" ".join(esc(t) for t in all_tags))

    text = "\n".join(parts).strip()
    # финальная чистка лишних двойных пустых строк
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    # Stage 13: caption-guard. Если Claude всё равно превысил бюджет и итог
    # длиннее лимита caption фото (1024 chars) — обрезаем mentor_part по
    # последнему абзацу до влезания. Beginner_mistake/lesson/partner/tags
    # сохраняем как ключевую структуру.
    if len(text) > TELEGRAM_PHOTO_CAPTION_LIMIT and mentor:
        text = _shrink_to_caption_limit(payload, post_type, include_partner, post_num)
    return text


def _shrink_to_caption_limit(
    payload: dict, post_type: str, include_partner: bool, post_num: int,
) -> str:
    """Перестраивает пост, по абзацам отрезая mentor_part с конца, пока итог
    не влезет в TELEGRAM_PHOTO_CAPTION_LIMIT. Возвращает финальный HTML.
    Если даже с пустым mentor не влазит — режет hamster_part.
    """
    mentor_full = (payload.get("mentor_part") or "").strip()
    paragraphs = [p.strip() for p in mentor_full.split("\n\n") if p.strip()]
    while paragraphs:
        paragraphs.pop()  # убираем последний абзац mentor_part
        trial_payload = dict(payload, mentor_part="\n\n".join(paragraphs))
        trial = _build_post_html_raw(trial_payload, post_type, include_partner, post_num)
        if len(trial) <= TELEGRAM_PHOTO_CAPTION_LIMIT:
            log.warning("post shrunk: mentor_part trimmed to %d paragraphs (final=%d chars)",
                        len(paragraphs), len(trial))
            return trial
    # mentor пустой — пробуем убрать hamster
    trial_payload = dict(payload, mentor_part="", hamster_part=None)
    trial = _build_post_html_raw(trial_payload, post_type, include_partner, post_num)
    if len(trial) <= TELEGRAM_PHOTO_CAPTION_LIMIT:
        log.warning("post shrunk: mentor+hamster removed (final=%d chars)", len(trial))
        return trial
    # совсем плохо — отдаём как есть, длинный split-flow в send_post_with_optional_image
    log.error("post still > %d chars even after shrink, will split", TELEGRAM_PHOTO_CAPTION_LIMIT)
    return _build_post_html_raw(payload, post_type, include_partner, post_num)


def _build_post_html_raw(
    payload: dict, post_type: str, include_partner: bool, post_num: int,
) -> str:
    """Внутренняя версия build_post_html без caption-guard (избегаем рекурсии)."""
    parts: list[str] = []
    human = esc(payload.get("human_part", "")).strip()
    hamster = esc(payload.get("hamster_part") or "").strip()
    mentor = esc(payload.get("mentor_part", "")).strip()
    mistake = esc(payload.get("beginner_mistake") or "").strip()
    lesson = esc(payload.get("lesson") or payload.get("conclusion") or "").strip()
    if human:
        parts.append(human)
    if hamster:
        parts += ["", "🐹 <b>Внутренний хомяк</b>", hamster]
    if mentor:
        parts += ["", "🤖 <b>AI-наставник</b>", mentor]
    if mistake:
        parts += ["", "⚠️ <b>Ошибка новичка</b>", mistake]
    if lesson:
        parts += ["", "📌 <b>Вывод</b>", lesson]
    q = payload.get("question")
    if q:
        parts += ["", "💬 " + esc(q)]
    if include_partner and PARTNER_URL:
        hook = PARTNER_HOOKS[post_num % len(PARTNER_HOOKS)]
        parts += ["", hook.format(url=esc(PARTNER_URL))]
    parts.append("")
    disclaimer_text = DISCLAIMER if post_type == "fallback_education" else DISCLAIMER_SHORT
    parts.append("<i>" + esc(disclaimer_text) + "</i>")
    tags = payload.get("hashtags") or []
    tags = [t if str(t).startswith("#") else f"#{t}" for t in tags]
    system_tags: list[str] = ["#честный_путь"]
    if hamster:
        system_tags.append("#не_будь_хомяком")
    else:
        system_tags.append("#ошибки_новичка")
    if post_type == "flash":
        system_tags.append("#flash")
    elif post_type == "fallback_education":
        system_tags.append("#термин_без_боли")
    all_tags = list(dict.fromkeys(tags + system_tags))
    parts += ["", " ".join(esc(t) for t in all_tags)]
    text = "\n".join(parts).strip()
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text


# =============================================================================
# VIDEO (lazy, off by default)
# =============================================================================

def make_video(image_path: Path, text: str, out_path: Path) -> Path | None:
    if not GENERATE_VIDEO:
        return None
    try:
        from moviepy.editor import ImageClip, TextClip, CompositeVideoClip  # type: ignore
        clip = ImageClip(str(image_path)).set_duration(6)
        txt = TextClip(text[:120], fontsize=40, color="white").set_position("center").set_duration(6)
        video = CompositeVideoClip([clip, txt])
        video.write_videofile(str(out_path), fps=24, logger=None)
        return out_path
    except Exception as e:
        log.warning("video generation failed: %s", e)
        return None


# =============================================================================
# PUBLISHER
# =============================================================================

class Publisher:
    def __init__(self):
        if not TELEGRAM_TOKEN:
            raise RuntimeError("TELEGRAM_TOKEN не задан в .env")
        if not CLAUDE_API_KEY:
            raise RuntimeError("CLAUDE_API_KEY не задан в .env")
        self.bot = Bot(token=TELEGRAM_TOKEN, session=_ThreadedResolverSession())
        self.market = Market()
        self.claude = Anthropic(api_key=CLAUDE_API_KEY)
        self.openai = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
        # Этап 1.4: убираем зависимость от глобала. MistakeTracker создаётся
        # локально, чтобы `--post-now` без scheduler не падал в fallback-ветке.
        self.mistake_tracker = MistakeTracker(
            themes_file=str(ROOT / "mistake_themes.json"),
            state_file=str(ROOT / "mistake_tracker_state.json"),
        )

    def _target_chat(self) -> str:
        if DRY_RUN:
            if not OWNER_CHAT_ID:
                raise RuntimeError("DRY_RUN=true, но OWNER_CHAT_ID не задан")
            return OWNER_CHAT_ID
        if not CHANNEL_ID:
            raise RuntimeError("CHANNEL_ID не задан, а DRY_RUN=false")
        return CHANNEL_ID

    async def _send(self, text: str, photo_path: Path | None) -> None:
        target = self._target_chat()
        prefix = "[DRY_RUN] " if DRY_RUN else ""
        full = prefix + text if prefix else text
        # Stage 12d — единая логика: photo+caption (с long-caption split при необходимости).
        # Не отправляем фото отдельным пустым сообщением.
        await send_post_with_optional_image(
            self.bot, target, full,
            str(photo_path) if photo_path else None,
            disable_web_page_preview=False,
        )

    async def close(self) -> None:
        await self.bot.session.close()

    async def publish(
        self,
        source: str = "scheduled",
        user_action: str | None = None,
        image_context: str | None = None,
        force_education: bool = False,
    ) -> None:
        state = load_state()
        post_num = int(state.get("post_count", 0)) + 1
        history = load_history()

        include_partner = bool(PARTNER_URL) and (post_num % PARTNER_EVERY_N == 0)
        need_question = (post_num % QUESTION_EVERY_N == 0)

        # --- market snapshot ---
        ticker = self.market.ticker()
        df = self.market.ohlcv("1h", 300)
        if df is not None:
            df = self.market.indicators(df)

        post_type = "market"
        mode = "normal"

        if force_education:
            # Stage 13: вечерний education-слот. Не зависит от рынка, мы просто
            # переходим в обучающий режим с темой из MistakeTracker.
            post_type = "fallback_education"
            mode = "fallback_education"
        elif not ticker or df is None or len(df) < 20:
            post_type = "fallback_education"
            mode = "fallback_education"
        elif ticker.get("change_24h") is not None and abs(ticker["change_24h"]) >= FLASH_THRESHOLD:
            post_type = "flash"
            mode = "flash"

        market_snapshot: dict = {}
        chart_path: Path | None = None

        if mode == "fallback_education":
            # Используем MistakeTracker для равномерного покрытия тем
            topic = self.mistake_tracker.get_next_topic()
            market_snapshot = {"fallback_topic": topic}
            # Запоминаем использование темы
            for tid, info in self.mistake_tracker.themes.items():
                if info["title"] == topic:
                    self.mistake_tracker.record_usage(tid)
                    break
        else:
            last = df.iloc[-1]
            def _f(col):
                v = last.get(col) if col in df.columns else None
                return float(v) if v is not None and pd.notna(v) else None

            market_snapshot = {
                "symbol": "BTC/USDT",
                "price": _f("Close"),
                "change_24h": ticker.get("change_24h"),
                "high_24h": ticker.get("high_24h"),
                "low_24h": ticker.get("low_24h"),
                "rsi": _f("rsi"),
                "ema50": _f("ema50"),
                "ema200": _f("ema200"),
                "volume_spike": self.market.volume_spike(df),
                "funding": self.market.funding(),
                "open_interest": self.market.open_interest(),
            }
            chart_path = await make_chart_tv(df, CHARTS_DIR)
            if chart_path is None:
                chart_file = CHARTS_DIR / f"chart_{datetime.utcnow():%Y%m%d_%H%M}.png"
                chart_path = make_chart(df, chart_file)

        # --- memory context ---
        memory_context = [
            {
                "datetime": h.get("datetime"),
                "post_type": h.get("post_type"),
                "short_summary": h.get("short_summary", ""),
            }
            for h in history[-HISTORY_LIMIT:]
        ]

        context = {
            "post_num": post_num,
            "post_type": post_type,
            "market": market_snapshot,
            "memory": memory_context,
            "user_action": user_action,
            "image_context": image_context,
            "source": source,
            "need_partner": include_partner,
        }
        # Stage 10+: мягкая подсказка Claude по контент-миксу (target 40/20/15/15/10).
        # Подавляется для flash mode и когда сработали priority-события — это не должно
        # ломать срочный контент.
        mix_hint = _content_mix_hint_block(allow=(mode != "flash"))
        if mix_hint:
            context["content_mix_hint"] = mix_hint

        # --- Claude ---
        try:
            payload = ask_claude(self.claude, context, need_question=need_question, mode=mode)
        except Exception as e:
            log.exception("Claude failed: %s", e)
            return

        # Этап 2.6: pre-publish style guard. forbidden_words → блокируем
        # публикацию, шлём DM владельцу. Markers — soft warning, не блокировка.
        try:
            from core.styleguard_block import check_payload_or_reject
            ok_style, style_reason = check_payload_or_reject(payload, styleguard)
            if not ok_style:
                log.warning("style block: %s", style_reason)
                try:
                    await self.bot.send_message(
                        OWNER_CHAT_ID,
                        f"⛔ Style block: {style_reason}\n\n"
                        f"Пост не отправлен в канал.",
                    )
                except Exception:
                    pass
                return
        except Exception as e:
            log.warning("styleguard check failed (fail-open): %s", e)

        # --- image (по флагу + не чаще 1/N, flash может чаще) ---
        photo_path: Path | None = None
        frequency_ok = post_num - int(state.get("last_image_at", 0)) >= IMAGE_EVERY_N
        want_image = (
            GENERATE_IMAGES
            and self.openai is not None
            and bool(payload.get("should_generate_image"))
            and bool(payload.get("image_prompt"))
            and (mode == "flash" or frequency_ok)
        )
        if want_image:
            img_file = IMAGES_DIR / f"ai_{datetime.utcnow():%Y%m%d_%H%M}.png"
            generated = generate_image(self.openai, payload["image_prompt"], img_file)
            if generated:
                photo_path = generated
                state["last_image_at"] = post_num

        if photo_path is None and chart_path is not None:
            photo_path = chart_path

        # --- video (off by default) ---
        if GENERATE_VIDEO and photo_path:
            vid_file = VIDEOS_DIR / f"video_{datetime.utcnow():%Y%m%d_%H%M}.mp4"
            make_video(photo_path, payload.get("short_summary", ""), vid_file)

        # --- HTML + send ---
        text = build_post_html(
            payload, post_type=post_type,
            include_partner=include_partner, post_num=post_num,
        )

        try:
            await self._send(text, photo_path)
        except Exception as e:
            log.exception("Telegram send failed: %s", e)
            return

        # --- persist ---
        if include_partner:
            state["last_partner_at"] = post_num
        state["post_count"] = post_num
        save_state(state)

        append_history({
            "datetime": datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
            "post_type": post_type,
            "asset": market_snapshot.get("symbol", "-"),
            "market_snapshot": market_snapshot,
            "short_summary": payload.get("short_summary", ""),
            "final_text": text,
            "partner_used": bool(include_partner),
            "source": source,
        })

        # Stage 10+: content-mix tracker — DRY_RUN считается как published_to=owner
        _log_post_event(
            post_type,
            published_to=("channel" if not DRY_RUN else "owner"),
            title=(payload.get("short_summary") or "")[:120],
            source=source or "scheduled",
        )

        log.info(
            "post #%d опубликован: type=%s, dry=%s, partner=%s, img=%s",
            post_num, post_type, DRY_RUN, include_partner,
            bool(photo_path and photo_path.suffix == ".png" and "ai_" in photo_path.name),
        )


# =============================================================================
# WEBHOOK (off by default)
# =============================================================================

app = FastAPI()
_publisher_holder: dict = {"p": None}


@app.post("/webhook")
async def webhook(req: Request):
    if not ENABLE_WEBHOOK:
        raise HTTPException(status_code=404, detail="webhook disabled")
    secret = req.headers.get("X-Webhook-Secret") or req.query_params.get("secret")
    if not WEBHOOK_SECRET or secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="bad secret")
    try:
        data = await req.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")
    publisher: Publisher | None = _publisher_holder.get("p")
    if publisher is None:
        raise HTTPException(status_code=503, detail="publisher not ready")
    await publisher.publish(
        source=f"webhook",
        user_action=data.get("user_action"),
        image_context=data.get("image"),
    )
    return {"ok": True, "dry_run": DRY_RUN}
async def _safe_publish(publisher: Publisher, sentinel: Sentinel, source: str) -> None:
    """Обёртка для плановых публикаций с защитой Sentinel.

    source `scheduled_evening_education` форсирует education-режим (Stage 13).
    """
    force_education = source == "scheduled_evening_education"
    await sentinel.safe_execute(
        publisher.publish(source=source, force_education=force_education),
        context=source,
    )

async def _safe_mistake_report_job(bot: Bot, tracker: MistakeTracker):
    try:
        report = tracker.weekly_report()
        if OWNER_CHAT_ID:
            await bot.send_message(int(OWNER_CHAT_ID), report, parse_mode=ParseMode.HTML)
        log.info("Mistake tracker weekly report sent.")
    except Exception as e:
        log.exception("Mistake report failed: %s", e)

async def run_scheduler_forever() -> None:
    global styleguard, mistake_tracker

    publisher = Publisher()
    _publisher_holder["p"] = publisher

    # === Новые стражи ===
    sentinel = Sentinel(
        bot=publisher.bot,
        channel_id=publisher._target_chat(),
        owner_chat_id=int(OWNER_CHAT_ID),
        fallback_file=str(ROOT / "fallback_lessons.json")
    )
    styleguard = StyleGuard()
    # Этап 1.4: глобал mistake_tracker теперь зеркало publisher.mistake_tracker
    # (Publisher.__init__ создаёт его сам, не зависит от scheduler-инициализации).
    mistake_tracker = publisher.mistake_tracker

    # === Передаём трекер в админ-панель ===
    import admin_panel
    admin_panel.mistake_tracker = mistake_tracker

    sched = AsyncIOScheduler(timezone=SCHEDULER_TZ)
    # Stage 13: 10:00 ежедневно — market_chart; вечером 19:00 пн-сб —
    # education (выравнивание content-mix к плану 40/20/15/15/10);
    # вс 19:00 — weekly_diary (отдельным job ниже).
    sched.add_job(_safe_publish, "cron",
                  hour=POST_MORNING_HOUR, minute=0,
                  args=[publisher, sentinel, "scheduled_morning"])
    sched.add_job(_safe_publish, "cron",
                  day_of_week="mon-sat",
                  hour=POST_EVENING_HOUR, minute=0,
                  args=[publisher, sentinel, "scheduled_evening_education"])
    sched.add_job(
        _safe_mistake_report_job, "cron",
        day_of_week="sun", hour=12, minute=0,
        args=[publisher.bot, mistake_tracker]
    )

    # news scan job — включается только если ENABLE_NEWS=true в .env
    try:
        from news import NewsConfig as _NewsConfig
        _news_cfg = _NewsConfig.from_env()
        if _news_cfg.enable_news:
            sched.add_job(
                _safe_news_scan_job, "interval",
                minutes=max(10, _news_cfg.news_scan_interval_minutes),
                id="news_scan",
            )
            log.info("news scan job: каждые %d минут, порог impact=%d, dry_run=%s, channel=%s",
                     _news_cfg.news_scan_interval_minutes,
                     _news_cfg.news_min_impact_score,
                     _news_cfg.news_dry_run,
                     _news_cfg.news_publish_to_channel)
        else:
            log.info("ENABLE_NEWS=false — news scan job не активирован")
    except Exception as e:
        log.warning("не удалось инициализировать news scan job: %s", e)

    # Stage 10: author_note job — раз в день в 12:00 МСК; сам себя ограничит
    # квотой AUTHOR_NOTES_PER_WEEK. Превью идёт владельцу на ревью.
    try:
        from author_notes import AuthorNoteConfig as _AnCfg
        _an_cfg = _AnCfg.from_env()
        if _an_cfg.enable_author_notes:
            sched.add_job(
                _safe_author_note_job, "cron",
                hour=12, minute=0, id="author_note",
            )
            log.info("author_note job: 12:00 %s ежедневно | per_week=%d, dry_run=%s, review=%s",
                     SCHEDULER_TZ, _an_cfg.author_notes_per_week,
                     _an_cfg.author_note_dry_run, _an_cfg.author_note_review_required)
        else:
            log.info("ENABLE_AUTHOR_NOTES=false — author_note job не активирован")
    except Exception as e:
        log.warning("не удалось инициализировать author_note job: %s", e)

    # Stage 13: weekly_diary — воскресенье 19:00 МСК, превью владельцу
    try:
        from weekly_diary import WeeklyDiaryConfig as _WdCfg
        _wd_cfg = _WdCfg.from_env()
        if _wd_cfg.enable_weekly_diary:
            sched.add_job(
                _safe_weekly_diary_job, "cron",
                day_of_week="sun", hour=19, minute=0, id="weekly_diary",
            )
            log.info("weekly_diary job: вс 19:00 %s | dry_run=%s",
                     SCHEDULER_TZ, _wd_cfg.weekly_diary_dry_run)
        else:
            log.info("ENABLE_WEEKLY_DIARY=false — weekly_diary job не активирован")
    except Exception as e:
        log.warning("не удалось инициализировать weekly_diary job: %s", e)

    # auto-trade scan / tick jobs (Stage 7) — только если AUTO_TRADE_ENABLED=true
    try:
        from trading import TradingConfig as _TradingConfig
        _trade_cfg = _TradingConfig.from_env()
        if _trade_cfg.auto_trade_enabled and _trade_cfg.trading_mode == "paper":
            scan_min = max(15, _trade_cfg.auto_trade_scan_interval_minutes)
            tick_min = max(15, _trade_cfg.auto_trade_tick_interval_minutes)
            sched.add_job(
                _safe_auto_trade_scan_job, "interval",
                minutes=scan_min, id="auto_trade_scan",
            )
            sched.add_job(
                _safe_auto_trade_tick_job, "interval",
                minutes=tick_min, id="auto_trade_tick",
            )
            log.info(
                "auto-trade jobs ON: scan каждые %d мин, tick каждые %d мин | "
                "publish_mode=%s, channel=%s, claude_review=%s",
                scan_min, tick_min,
                _trade_cfg.trade_publish_mode,
                _trade_cfg.publish_trade_updates_to_channel,
                _trade_cfg.trade_claude_review,
            )
        else:
            log.info("AUTO_TRADE_ENABLED=false (или не paper-режим) — auto-trade jobs не активированы")
    except Exception as e:
        log.warning("не удалось инициализировать auto-trade jobs: %s", e)

    # Stage 8a: expire confirmations + live reconcile
    try:
        from trading import TradingConfig as _TradingConfig
        _trade_cfg = _TradingConfig.from_env()
        # expire job — нужен всегда, когда вообще создаются confirm-планы
        # (даже без RW-ключей, чтобы протухшие планы не висели вечно)
        sched.add_job(
            _safe_expire_confirmations_job, "interval",
            minutes=max(1, min(5, _trade_cfg.confirm_timeout_minutes)),
            id="confirm_expire",
        )
        # reconcile job — только при наличии RW-ключей
        if _trade_cfg.gate_api_key_rw and _trade_cfg.gate_api_secret_rw:
            sched.add_job(
                _safe_live_reconcile_job, "interval",
                minutes=max(1, _trade_cfg.live_reconcile_interval_minutes),
                id="live_reconcile",
            )
            log.info("Stage 8a: confirm expire (1-5 min) + live reconcile каждые %d мин",
                     _trade_cfg.live_reconcile_interval_minutes)
        else:
            log.info("Stage 8a: confirm expire job ON; live reconcile OFF (нет GATE_API_KEY_RW)")

        # warning если live ошибочно включён до обкатки confirm
        if _trade_cfg.live_trading_enabled and not _trade_cfg.confirm_mode_proven:
            log.warning(
                "LIVE_TRADING_ENABLED=true, но CONFIRM_MODE_PROVEN=false → "
                "live ИГНОРИРУЕТСЯ. Сначала обкатай confirm."
            )
            try:
                _warn_bot = _new_trading_bot()
                async def _warn():
                    try:
                        await _owner_dm(
                            _warn_bot,
                            "<b>⚠️ [BOOT]</b> LIVE_TRADING_ENABLED=true, но "
                            "CONFIRM_MODE_PROVEN=false. Live игнорируется."
                        )
                    finally:
                        await _warn_bot.session.close()
                asyncio.create_task(_warn())
            except Exception:
                pass
    except Exception as e:
        log.warning("не удалось инициализировать Stage 8a jobs: %s", e)

    # Stage 12c — one-shot persistence-recovery на старте, ДО первого interval-tick.
    # После долгого даунтайма не ждём interval (5–15 мин), а сразу:
    # - снимаем awaiting_confirmation, висящие дольше CONFIRM_TIMEOUT_MINUTES;
    # - сверяем live state с биржей (если есть RW-ключи).
    # Любые исключения здесь не валят запуск — это best-effort recovery.
    async def _persistence_recovery_on_startup() -> None:
        try:
            await _safe_expire_confirmations_job()
        except Exception as e:
            log.warning("startup expire_confirmations failed: %s", e)
        try:
            await _safe_live_reconcile_job()
        except Exception as e:
            log.warning("startup live_reconcile failed: %s", e)
        # дашборд для владельца, чтобы было видно что бот поднялся и что подобрал state
        try:
            from news import DraftStore as _NDS
            from trading import PaperBroker as _PB, TradingConfig as _TC, ConfirmTradesStore as _CTS, LiveTradesStore as _LTS
            ncfg = _TC.from_env()
            paper = _PB(ncfg, PAPER_TRADES_FILE)
            confirm = _CTS(CONFIRM_TRADES_FILE)
            live = _LTS(LIVE_TRADES_FILE)
            news_drafts = _NDS(NEWS_DRAFTS_FILE)
            pending_news = len(news_drafts.list_pending())
            active_paper = len(paper.active_trades())
            pending_confirm = len(confirm.pending())
            active_live = len(live.active_or_pending_live())
            awaiting_edit = _state_get_awaiting_news_edit() or "—"
            log.info(
                "Stage 12c boot recovery: pending_news=%d active_paper=%d "
                "pending_confirm=%d active_live=%d awaiting_news_edit_for=%s",
                pending_news, active_paper, pending_confirm, active_live, awaiting_edit,
            )
        except Exception as e:
            log.warning("startup persistence summary crashed: %s", e)

    asyncio.create_task(_persistence_recovery_on_startup())

    sched.start()

    log.info(
        "scheduler started: %s %02d:00 / %02d:00 (%s) | DRY_RUN=%s | WEBHOOK=%s | IMAGES=%s",
        SCHEDULER_TZ, POST_MORNING_HOUR, POST_EVENING_HOUR, SCHEDULER_TZ,
        DRY_RUN, ENABLE_WEBHOOK, GENERATE_IMAGES,
    )

    # Stage 8a: aiogram Dispatcher для callback-кнопок confirm-mode.
    # Поднимаем второй Bot specifically для polling, чтобы не конфликтовать с
    # publisher.bot (он используется для send_message). Это безопасно —
    # один токен может polling'ить только из одного процесса, но двух Bot-объектов
    # в одном процессе достаточно: polling делает только dp_bot.
    dp = Dispatcher()
    _register_confirm_callbacks(dp)
    _register_news_callbacks(dp)
    _register_author_note_callbacks(dp)
    _register_weekly_diary_callbacks(dp)
    _register_trade_visual_handlers(dp)
    dp_bot = Bot(token=TELEGRAM_TOKEN, session=_ThreadedResolverSession())
    polling_task: asyncio.Task | None = None

    try:
        if ENABLE_WEBHOOK:
            log.info("webhook listening on %s:%d", WEBHOOK_HOST, WEBHOOK_PORT)
            config = uvicorn.Config(app, host=WEBHOOK_HOST, port=WEBHOOK_PORT, log_level="info")
            server = uvicorn.Server(config)
            await server.serve()
        else:
            # запускаем polling в отдельной таске, и сидим в idle-loop
            polling_task = asyncio.create_task(
                dp.start_polling(dp_bot, allowed_updates=["callback_query", "message"])
            )
            log.info("Telegram Dispatcher polling started (для confirm-mode кнопок)")
            while True:
                await asyncio.sleep(3600)
    finally:
        sched.shutdown(wait=False)
        if polling_task:
            polling_task.cancel()
            try:
                await polling_task
            except (asyncio.CancelledError, Exception):
                pass
        try:
            await dp_bot.session.close()
        except Exception:
            pass
        await publisher.close()


async def run_once() -> None:
    publisher = Publisher()
    try:
        await publisher.publish(source="manual")
    finally:
        await publisher.close()


# =============================================================================
# TRADING CLI (paper-broker, backtest, auto-trade, channel publish)
# =============================================================================

def _new_trading_bot() -> Bot:
    """Минимальный aiogram Bot — только чтобы слать DM/канал-пост."""
    if not TELEGRAM_TOKEN:
        raise RuntimeError("TELEGRAM_TOKEN не задан в .env")
    return Bot(token=TELEGRAM_TOKEN, session=_ThreadedResolverSession())


async def _owner_dm(bot: Bot, text: str) -> None:
    if not OWNER_CHAT_ID:
        log.warning("OWNER_CHAT_ID не задан — пропускаю DM")
        log.info("DM text (no owner):\n%s", text)
        return
    await bot.send_message(OWNER_CHAT_ID, text, parse_mode=ParseMode.HTML,
                           disable_web_page_preview=False)


def _make_trade_send_fn(bot: Bot):
    """Возвращает callable (chat_id, text) -> awaitable для orchestrator.SendFn."""
    async def _send(chat_id: str, text: str) -> None:
        if not chat_id:
            log.warning("trade send: chat_id пустой, skip")
            return
        await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML,
                               disable_web_page_preview=False)
    return _send


# ---------- state helpers для trade-блока ---------------------------------

def _today_utc_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")


def _state_get_trade_channel_posts_today() -> int:
    """Возвращает количество торговых постов в канал за сегодня (UTC).

    Если в state.json дата не сегодня — считаем 0 (счётчик протух).
    """
    s = load_state()
    if s.get("trade_channel_posts_date") != _today_utc_iso():
        return 0
    try:
        return int(s.get("trade_channel_posts_today") or 0)
    except (TypeError, ValueError):
        return 0


def _state_increment_trade_channel_posts_today() -> None:
    s = load_state()
    today = _today_utc_iso()
    if s.get("trade_channel_posts_date") != today:
        s["trade_channel_posts_today"] = 1
        s["trade_channel_posts_date"] = today
    else:
        s["trade_channel_posts_today"] = int(s.get("trade_channel_posts_today") or 0) + 1
    save_state(s)


def _state_set_last_scan_at(ts: str) -> None:
    s = load_state()
    s["last_trade_scan_at"] = ts
    save_state(s)


def _state_set_last_tick_at(ts: str) -> None:
    s = load_state()
    s["last_trade_tick_at"] = ts
    save_state(s)


def _make_trade_state_helpers():
    from trading import StateHelpers
    return StateHelpers(
        get_channel_posts_today=_state_get_trade_channel_posts_today,
        increment_channel_posts_today=_state_increment_trade_channel_posts_today,
        set_last_scan_at=_state_set_last_scan_at,
        set_last_tick_at=_state_set_last_tick_at,
    )


def _make_trade_market_snapshot() -> dict:
    """Та же выжимка BTC/ETH, что в news. Используется как контекст для Claude review."""
    return _market_snapshot_for_news()


def _build_trade_ctx_kwargs(*, with_claude: bool):
    """Собирает kwargs, общие для всех команд оркестратора."""
    from trading import TradingConfig
    cfg = TradingConfig.from_env()
    if cfg.trading_mode != "paper":
        raise RuntimeError(f"TRADING_MODE={cfg.trading_mode}: реализован только paper")
    claude = Anthropic(api_key=CLAUDE_API_KEY) if with_claude and CLAUDE_API_KEY else None
    return cfg, claude


# ---------- CLI: одиночные команды ----------------------------------------

# =============================================================================
# Stage 11 — TRADE VISUALS HOOK
# =============================================================================
TRADE_VISUALS_DIR = OUTPUTS / "trade_visuals"
GATE_SCREENSHOTS_DIR = OUTPUTS / "gate_screenshots"
TRADE_MSG_INDEX_CAP = 100   # last N entries in state.trade_message_index


# ----- state helpers -----

def _state_set_gate_screenshot(trade_id: str, path: str) -> None:
    if not trade_id:
        return
    s = load_state()
    m = s.get("gate_screenshots") or {}
    if not isinstance(m, dict):
        m = {}
    m[trade_id] = path
    s["gate_screenshots"] = m
    save_state(s)


def _state_get_gate_screenshot(trade_id: str) -> str | None:
    if not trade_id:
        return None
    s = load_state()
    m = s.get("gate_screenshots") or {}
    if not isinstance(m, dict):
        return None
    p = m.get(trade_id)
    if p and Path(p).exists():
        return p
    return None


def _state_remember_trade_message(message_id: int, trade_id: str) -> None:
    """Map: telegram message_id → trade_id, чтобы reply на сообщение сделки
    мог идентифицировать trade без явного аргумента."""
    if not message_id or not trade_id:
        return
    s = load_state()
    idx = s.get("trade_message_index") or {}
    if not isinstance(idx, dict):
        idx = {}
    idx[str(message_id)] = trade_id
    # rolling cap
    if len(idx) > TRADE_MSG_INDEX_CAP:
        keys = list(idx.keys())[-TRADE_MSG_INDEX_CAP:]
        idx = {k: idx[k] for k in keys}
    s["trade_message_index"] = idx
    save_state(s)


def _state_lookup_trade_by_message(message_id: int) -> str | None:
    if not message_id:
        return None
    s = load_state()
    idx = s.get("trade_message_index") or {}
    if not isinstance(idx, dict):
        return None
    return idx.get(str(message_id))


def _lookup_trade_by_id(trade_id: str):
    """Найти сделку (PaperTrade или ConfirmTrade) по id в любом из хранилищ.
    Возвращает объект (с duck-typing) или None."""
    try:
        from trading import PaperBroker, TradingConfig
        cfg = TradingConfig.from_env()
        broker = PaperBroker(cfg, PAPER_TRADES_FILE)
        for t in (broker.load_open_trades() or []):
            if getattr(t, "id", None) == trade_id:
                return t
    except Exception:
        pass
    try:
        from trading import TradeJournal
        journal = TradeJournal(TRADE_JOURNAL_FILE)
        # journal — лог событий, не объекты сделок; в стандартном API нет find().
        # Достаём из paper_trades.json последние закрытые через broker.load_all() если есть.
        # Если нет — пропускаем.
    except Exception:
        pass
    try:
        from trading import ConfirmTradesStore
        store = ConfirmTradesStore(CONFIRM_TRADES_FILE)
        t = store.find(trade_id)
        if t is not None:
            return t
    except Exception:
        pass
    return None


def _last_trade():
    """Самая последняя сделка (по timestamp). Сначала открытые paper, потом confirm."""
    try:
        from trading import PaperBroker, TradingConfig
        cfg = TradingConfig.from_env()
        broker = PaperBroker(cfg, PAPER_TRADES_FILE)
        opens = broker.load_open_trades() or []
        if opens:
            return sorted(opens, key=lambda t: getattr(t, "created_at", "") or "", reverse=True)[0]
    except Exception:
        pass
    try:
        from trading import ConfirmTradesStore
        trades = ConfirmTradesStore(CONFIRM_TRADES_FILE).load() or []
        if trades:
            return sorted(trades, key=lambda t: getattr(t, "created_at", "") or "", reverse=True)[0]
    except Exception:
        pass
    return None


async def _maybe_send_trade_visual(
    bot: Bot,
    trade_obj,
    *,
    event_type: str,
    publish_to_channel: bool = False,
) -> None:
    """Stage 11: hybrid trade visual.

    1. Generated trade-card (всегда, если ENABLE_TRADE_VISUALS=true)
    2. Gate.io screenshot — приоритет:
       a) manual: владелец прикрепил через /attach_gate_screenshot → state.gate_screenshots
       b) browser: только если GATE_SCREENSHOT_MODE=browser → Playwright-capture
       c) off / нет manual + не browser → пропускаем 2-е изображение

    Запоминает msg_id → trade_id для последующих /attach_gate_screenshot reply'ев.
    """
    try:
        from trade_visuals import (
            TradeVisualConfig, compose_trade_payload,
            save_trade_visual, build_trade_summary_card,
            capture_gate_screenshot,
        )
        cfg = TradeVisualConfig.from_env()
        if not cfg.enable_trade_visuals:
            return
        payload = compose_trade_payload(trade_obj)
        trade_id = str(payload.get("id") or "")

        png_path = save_trade_visual(
            payload=payload,
            out_dir=TRADE_VISUALS_DIR,
            bars=cfg.trade_visual_bars,
            timeframe=cfg.trade_visual_timeframe,
        )
        if not png_path:
            log.warning("trade visual: не удалось сгенерировать PNG (нет OHLCV?)")
            return

        head_emoji = "📈" if event_type == "opened" else "📊"
        head = ("Открыта" if event_type == "opened" else "Закрыта")
        if event_type == "closed":
            reason = (payload.get("close_reason") or "").lower()
            if reason in ("tp", "take_profit"):
                head = "Закрыта по TP"
            elif reason in ("sl", "stop_loss"):
                head = "Закрыта по SL"
            elif reason in ("manual", "manual_close"):
                head = "Закрыта вручную"
            elif reason == "expired":
                head = "Сделка истекла"

        primary_caption = (
            f"<b>{head_emoji} {head}</b>\n"
            + build_trade_summary_card(payload)
            + (f"\n\n<code>{html.escape(trade_id, quote=False)}</code>" if trade_id else "")
            + "\n\n<i>Не финсовет. Это дневник обучения и AI-разбор.</i>"
        )
        secondary_caption = (
            "📷 <b>Скрин Gate.io</b>\n"
            "На графике — логика сделки. На скрине — фактическое исполнение."
        )

        # ---- 1) generated trade-card ----
        # Stage 12d: длинный caption (build_trade_summary_card иногда >1024) уходит как
        # photo + short caption + полный текст отдельным сообщением. Короткий — прямо в caption.
        primary_title = f"Сделка {payload.get('symbol','')} {payload.get('direction','')}".strip()
        primary_brief = payload.get("short_summary") or ""
        if OWNER_CHAT_ID:
            try:
                # для запоминания msg_id (reply detection) шлём вручную, если caption помещается;
                # иначе — split путь, тогда reply будет на полный текст.
                if len(primary_caption) <= PHOTO_CAPTION_SAFE_LIMIT:
                    msg = await bot.send_photo(
                        OWNER_CHAT_ID, FSInputFile(str(png_path)),
                        caption=primary_caption, parse_mode=ParseMode.HTML,
                    )
                    if msg and trade_id:
                        _state_remember_trade_message(int(msg.message_id), trade_id)
                else:
                    short = _build_short_caption(primary_caption, title=primary_title, brief=primary_brief)
                    await bot.send_photo(
                        OWNER_CHAT_ID, FSInputFile(str(png_path)),
                        caption=short, parse_mode=ParseMode.HTML,
                    )
                    msg = await bot.send_message(
                        OWNER_CHAT_ID, primary_caption,
                        parse_mode=ParseMode.HTML, disable_web_page_preview=True,
                    )
                    if msg and trade_id:
                        _state_remember_trade_message(int(msg.message_id), trade_id)
            except Exception as e:
                log.warning("trade visual: send to OWNER failed: %s", e)

        if publish_to_channel and cfg.publish_trade_visuals_to_channel and CHANNEL_ID:
            try:
                await send_post_with_optional_image(
                    bot, CHANNEL_ID, primary_caption,
                    str(png_path),
                    disable_web_page_preview=True,
                    title=primary_title,
                    brief=primary_brief,
                )
            except Exception as e:
                log.warning("trade visual: send to CHANNEL failed: %s", e)

        # ---- 2) Gate.io screenshot (manual priority, browser fallback) ----
        if not cfg.gate_enabled_for(event_type):
            return

        gate_png: str | None = None
        # 2a — manual-attached
        if trade_id:
            mp = _state_get_gate_screenshot(trade_id)
            if mp:
                gate_png = mp
                log.info("trade visual: использую manual gate screenshot для %s", trade_id)

        # 2b — browser-capture (только при mode=browser)
        if not gate_png and cfg.gate_browser_capture_allowed:
            try:
                captured = await asyncio.to_thread(
                    capture_gate_screenshot, payload, GATE_SCREENSHOTS_DIR
                )
                if captured and Path(captured).exists():
                    gate_png = str(captured)
            except Exception as e:
                log.warning("gate browser-capture failed (non-fatal): %s", e)

        if not gate_png:
            log.info("trade visual: 2-е изображение пропущено (mode=%s, manual_attached=%s, browser_allowed=%s)",
                     cfg.gate_screenshot_mode,
                     bool(trade_id and _state_get_gate_screenshot(trade_id)),
                     cfg.gate_browser_capture_allowed)
            return

        if OWNER_CHAT_ID:
            try:
                await bot.send_photo(
                    OWNER_CHAT_ID, FSInputFile(str(gate_png)),
                    caption=secondary_caption, parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                log.warning("gate screenshot: send OWNER failed: %s", e)
        if (publish_to_channel
                and cfg.publish_trade_visuals_to_channel
                and CHANNEL_ID):
            try:
                await bot.send_photo(
                    CHANNEL_ID, FSInputFile(str(gate_png)),
                    caption=secondary_caption, parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                log.warning("gate screenshot: send CHANNEL failed: %s", e)
    except Exception as e:
        log.warning("trade visual hook crashed (non-fatal): %s", e)


def _register_trade_visual_handlers(dp: Dispatcher) -> None:
    """Stage 11: /attach_gate_screenshot для прикрепления manual-скрина к сделке.

    Принимаем два варианта:
    - photo с caption '/attach_gate_screenshot <trade_id>'
    - photo как reply на сообщение бота с trade_id (mapping в state.trade_message_index);
      caption '/attach_gate_screenshot' можно опустить (если нет — берём reply target)
    """
    @dp.message(F.photo)
    async def on_photo(message):
        if not OWNER_CHAT_ID:
            return
        if str(message.from_user.id) != str(OWNER_CHAT_ID).lstrip("@"):
            return
        caption = (message.caption or "").strip()
        reply = message.reply_to_message
        trade_id: str | None = None

        # 1) explicit: /attach_gate_screenshot <id>
        if caption.startswith("/attach_gate_screenshot"):
            parts = caption.split(maxsplit=1)
            if len(parts) == 2 and parts[1].strip():
                trade_id = parts[1].strip()
            elif reply is not None:
                trade_id = _state_lookup_trade_by_message(int(reply.message_id))
            if not trade_id:
                try:
                    await message.reply(
                        "Использование:\n"
                        "<code>/attach_gate_screenshot &lt;trade_id&gt;</code>\n\n"
                        "Или ответь этой командой/фото на сообщение бота с trade-card.",
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    pass
                return
        # 2) implicit: фото reply'ом на trade-card без caption — берём по mapping
        elif reply is not None:
            trade_id = _state_lookup_trade_by_message(int(reply.message_id))
            if not trade_id:
                # это не attach — просто фото, не наше дело
                return
        else:
            # обычное фото без caption и не reply — игнорируем
            return

        # скачиваем самое большое фото
        try:
            ph = max(message.photo, key=lambda p: (p.width or 0) * (p.height or 0))
            GATE_SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            safe_id = "".join(c for c in trade_id if c.isalnum() or c in "-_")[:32]
            out_path = GATE_SCREENSHOTS_DIR / f"manual_{safe_id}_{ts}.jpg"
            await message.bot.download(ph, destination=out_path)
            _state_set_gate_screenshot(trade_id, str(out_path))
        except Exception as e:
            log.exception("attach_gate_screenshot: download failed: %s", e)
            try:
                await message.reply(f"❌ Не удалось сохранить фото: {html.escape(str(e), quote=False)}",
                                    parse_mode=ParseMode.HTML)
            except Exception:
                pass
            return

        try:
            await message.reply(
                f"✅ Скрин Gate.io прикреплён к сделке <code>{html.escape(trade_id, quote=False)}</code>.\n"
                f"<i>{html.escape(str(out_path), quote=False)}</i>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


async def _send_trade_visuals_for_result(bot: Bot, result: dict) -> None:
    """Достаёт opened/closed из стандартного result паркета scan/tick/run_trade_now
    и шлёт визуалы. Безопасно при отсутствии ENABLE_TRADE_VISUALS."""
    if not isinstance(result, dict):
        return
    opened = result.get("opened")
    if opened:
        await _maybe_send_trade_visual(bot, opened, event_type="opened",
                                       publish_to_channel=False)
    for closed_trade in (result.get("closed") or []):
        await _maybe_send_trade_visual(bot, closed_trade, event_type="closed",
                                       publish_to_channel=True)


async def run_render_trade_visual_cmd(trade_id: str | None) -> None:
    """Stage 11 CLI:
        --render-trade-visual <id>     — найти сделку и отрендерить trade-card
        --render-last-trade-visual     — то же для самой последней сделки

    Отправляет в OWNER (если задан) + печатает путь к PNG.
    """
    trade = _last_trade() if not trade_id else _lookup_trade_by_id(trade_id)
    if trade is None:
        print(f"Сделка не найдена: {trade_id or 'last'}")
        return
    bot = _new_trading_bot() if OWNER_CHAT_ID else None
    try:
        if bot is not None:
            await _maybe_send_trade_visual(
                bot, trade,
                event_type=("closed" if (getattr(trade, "status", "") or "").lower().startswith("closed") else "opened"),
                publish_to_channel=False,
            )
        # печатаем путь к свежесгенерированному PNG (последний файл в каталоге)
        try:
            from trade_visuals import compose_trade_payload, save_trade_visual, TradeVisualConfig
            cfg = TradeVisualConfig.from_env()
            payload = compose_trade_payload(trade)
            png = save_trade_visual(
                payload=payload, out_dir=TRADE_VISUALS_DIR,
                bars=cfg.trade_visual_bars, timeframe=cfg.trade_visual_timeframe,
            )
            print(f"saved: {png}")
        except Exception as e:
            print(f"render error: {e}")
    finally:
        if bot is not None:
            await bot.session.close()


async def run_trade_scan_now_cmd() -> None:
    from trading import TradeContext, scan_for_new_setup
    cfg, claude = _build_trade_ctx_kwargs(with_claude=cfg_use_claude_for_trades())
    bot = _new_trading_bot()
    try:
        ctx = TradeContext(
            config=cfg,
            trades_path=PAPER_TRADES_FILE,
            journal_path=TRADE_JOURNAL_FILE,
            owner_chat_id=OWNER_CHAT_ID,
            channel_id=CHANNEL_ID,
            send_fn=_make_trade_send_fn(bot),
            state=_make_trade_state_helpers(),
            claude=claude,
            claude_model=CLAUDE_MODEL,
            market_snapshot_provider=_make_trade_market_snapshot,
        )
        result = await scan_for_new_setup(ctx, auto=False)
        log.info("trade-scan-now result: %s", _safe_log_dict(result))
        await _send_trade_visuals_for_result(bot, result)
    finally:
        await bot.session.close()


async def run_trade_tick_now_cmd() -> None:
    from trading import TradeContext, tick_open_trades
    cfg, claude = _build_trade_ctx_kwargs(with_claude=cfg_use_claude_for_trades())
    bot = _new_trading_bot()
    try:
        ctx = TradeContext(
            config=cfg,
            trades_path=PAPER_TRADES_FILE,
            journal_path=TRADE_JOURNAL_FILE,
            owner_chat_id=OWNER_CHAT_ID,
            channel_id=CHANNEL_ID,
            send_fn=_make_trade_send_fn(bot),
            state=_make_trade_state_helpers(),
            claude=claude,
            claude_model=CLAUDE_MODEL,
            market_snapshot_provider=_make_trade_market_snapshot,
        )
        result = await tick_open_trades(ctx)
        log.info("trade-tick-now: closed=%d, still_active=%d",
                 len(result.get("closed", []) or []),
                 len(result.get("still_active", []) or []))
        await _send_trade_visuals_for_result(bot, result)
    finally:
        await bot.session.close()


async def run_trade_now_cmd() -> None:
    """Back-compat: tick + scan."""
    from trading import run_trade_now
    cfg, claude = _build_trade_ctx_kwargs(with_claude=cfg_use_claude_for_trades())
    bot = _new_trading_bot()
    try:
        result = await run_trade_now(
            config=cfg,
            trades_path=PAPER_TRADES_FILE,
            journal_path=TRADE_JOURNAL_FILE,
            owner_chat_id=OWNER_CHAT_ID,
            channel_id=CHANNEL_ID,
            send_fn=_make_trade_send_fn(bot),
            state=_make_trade_state_helpers(),
            claude=claude,
            claude_model=CLAUDE_MODEL,
            market_snapshot_provider=_make_trade_market_snapshot,
            auto=False,
        )
        log.info("trade-now result: %s", _safe_log_dict(result))
        await _send_trade_visuals_for_result(bot, result)
    finally:
        await bot.session.close()


async def run_trade_review_last_cmd() -> None:
    from trading import run_review_last_trade
    cfg, claude = _build_trade_ctx_kwargs(with_claude=True)
    bot = _new_trading_bot()
    try:
        result = await run_review_last_trade(
            config=cfg,
            trades_path=PAPER_TRADES_FILE,
            journal_path=TRADE_JOURNAL_FILE,
            owner_chat_id=OWNER_CHAT_ID,
            channel_id=CHANNEL_ID,
            send_fn=_make_trade_send_fn(bot),
            claude=claude,
            claude_model=CLAUDE_MODEL,
            market_snapshot_provider=_make_trade_market_snapshot,
        )
        log.info("trade-review-last: %s", result)
    finally:
        await bot.session.close()


async def run_publish_last_trade_cmd(dry_run: bool = False) -> None:
    from trading import publish_last_trade
    cfg, claude = _build_trade_ctx_kwargs(with_claude=cfg_use_claude_for_trades())
    bot = _new_trading_bot()
    try:
        result = await publish_last_trade(
            config=cfg,
            trades_path=PAPER_TRADES_FILE,
            journal_path=TRADE_JOURNAL_FILE,
            owner_chat_id=OWNER_CHAT_ID,
            channel_id=CHANNEL_ID,
            send_fn=_make_trade_send_fn(bot),
            state=_make_trade_state_helpers(),
            claude=claude,
            claude_model=CLAUDE_MODEL,
            market_snapshot_provider=_make_trade_market_snapshot,
            dry_run=dry_run or DRY_RUN,
        )
        log.info("publish-last-trade: %s", result)
        # Stage 10+: учёт в контент-миксе. publish_last_trade сам решает «канал vs DM»
        # по dry_run; считаем по нему.
        try:
            r = result or {}
            decision = r.get("decision") or r.get("status") or ""
            went_to_channel = (
                bool(r.get("published_channel"))
                or decision in ("published_channel", "published")
                or (not (dry_run or DRY_RUN))
            )
            _log_post_event(
                "trade_review",
                published_to="channel" if went_to_channel else "owner",
                title=(r.get("symbol") or r.get("trade_id") or "trade")[:120],
                source="publish_last_trade_cli",
            )
        except Exception:
            pass
    finally:
        await bot.session.close()


async def run_paper_backtest_cmd(bars: int) -> None:
    from trading import run_paper_backtest
    from trading import TradingConfig
    cfg = TradingConfig.from_env()
    bot: Bot | None = None
    try:
        bot = _new_trading_bot() if OWNER_CHAT_ID else None
    except Exception as e:
        log.warning("не удалось поднять Telegram Bot для отчёта: %s", e)
        bot = None

    async def _send(text: str) -> None:
        if bot is not None:
            await _owner_dm(bot, text)

    try:
        await run_paper_backtest(
            config=cfg,
            bars=bars,
            trades_path=PAPER_TRADES_FILE,
            journal_path=TRADE_JOURNAL_FILE,
            send_dm=_send if bot is not None else None,
        )
    finally:
        if bot is not None:
            await bot.session.close()


# ---------- helpers --------------------------------------------------------

def cfg_use_claude_for_trades() -> bool:
    """Включён ли Claude для trade-разборов: по env-флагу TRADE_CLAUDE_REVIEW + наличие ключа."""
    if not CLAUDE_API_KEY:
        return False
    raw = os.getenv("TRADE_CLAUDE_REVIEW", "true").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _safe_log_dict(d) -> str:
    try:
        return json.dumps(d, ensure_ascii=False, default=str)[:500]
    except Exception:
        return str(d)[:500]


# ---------- scheduler jobs (Stage 7) ---------------------------------------

async def _safe_auto_trade_scan_job() -> None:
    """Scheduler job: каждые AUTO_TRADE_SCAN_INTERVAL_MINUTES.

    Пропускаем если AUTO_TRADE_ENABLED=false. Не открываем больше одной активной сделки.
    DM при no_trade не шлём (auto=True).
    """
    try:
        from trading import TradingConfig, TradeContext, scan_for_new_setup
        cfg = TradingConfig.from_env()
        if not cfg.auto_trade_enabled:
            return
        if cfg.trading_mode != "paper":
            log.warning("auto_trade_scan: TRADING_MODE=%s, не paper — skip", cfg.trading_mode)
            return
        if cfg.live_trading_enabled:
            log.warning("auto_trade_scan: LIVE_TRADING_ENABLED=true — skip (этот PR только paper)")
            return

        bot = _new_trading_bot()
        try:
            claude = Anthropic(api_key=CLAUDE_API_KEY) if cfg_use_claude_for_trades() else None
            ctx = TradeContext(
                config=cfg,
                trades_path=PAPER_TRADES_FILE,
                journal_path=TRADE_JOURNAL_FILE,
                owner_chat_id=OWNER_CHAT_ID,
                channel_id=CHANNEL_ID,
                send_fn=_make_trade_send_fn(bot),
                state=_make_trade_state_helpers(),
                claude=claude,
                claude_model=CLAUDE_MODEL,
                market_snapshot_provider=_make_trade_market_snapshot,
            )
            res = await scan_for_new_setup(ctx, auto=True)
            log.info("auto_trade_scan: %s", _safe_log_dict(res))
        finally:
            await bot.session.close()
    except Exception as e:
        log.exception("auto_trade_scan_job crashed: %s", e)


# =============================================================================
# STAGE 8a — CONFIRM-MODE (real Gate.io futures с обязательной кнопкой)
# =============================================================================

def _keyboard_from_dict(d: dict) -> InlineKeyboardMarkup:
    """Преобразует {'inline_keyboard': [[{'text','callback_data'}, ...]]} в aiogram InlineKeyboardMarkup."""
    rows = []
    for row in d.get("inline_keyboard", []):
        buttons = []
        for btn in row:
            buttons.append(InlineKeyboardButton(
                text=btn["text"],
                callback_data=btn["callback_data"],
            ))
        rows.append(buttons)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _make_confirm_send_buttons(bot: Bot):
    """Возвращает callable (text, keyboard_dict) → message_id."""
    async def _send(text: str, keyboard: dict) -> int | None:
        if not OWNER_CHAT_ID:
            log.warning("OWNER_CHAT_ID не задан — confirm message не отправлено")
            return None
        msg = await bot.send_message(
            OWNER_CHAT_ID, text,
            parse_mode=ParseMode.HTML,
            reply_markup=_keyboard_from_dict(keyboard),
        )
        return msg.message_id
    return _send


async def run_confirm_trade_now_cmd() -> None:
    from trading import TradingConfig, confirm_trade_now
    cfg = TradingConfig.from_env()
    bot = _new_trading_bot()
    try:
        result = await confirm_trade_now(
            config=cfg,
            confirm_path=CONFIRM_TRADES_FILE,
            live_path=LIVE_TRADES_FILE,
            journal_path=LIVE_TRADE_JOURNAL_FILE,
            send_dm=lambda t: _owner_dm(bot, t),
            send_buttons=_make_confirm_send_buttons(bot),
        )
        log.info("confirm-trade-now: %s", _safe_log_dict(result))
        if not result.get("ok"):
            log.warning("confirm-trade-now не создал план: %s", result.get("reason"))
        else:
            # Stage 11: визуал плана идёт владельцу как complement к confirm-сообщению
            try:
                from trading import ConfirmTradesStore
                store = ConfirmTradesStore(CONFIRM_TRADES_FILE)
                trade = store.find(result.get("trade_id") or "")
                if trade is not None:
                    await _maybe_send_trade_visual(bot, trade, event_type="opened",
                                                   publish_to_channel=False)
            except Exception as e:
                log.warning("trade visual (confirm) failed: %s", e)
            log.warning(
                "Кнопки отправлены в OWNER_CHAT_ID. Они работают только когда "
                "запущен scheduler (`python bot.py` без флагов) — он держит Dispatcher polling."
            )
    finally:
        await bot.session.close()


async def run_expire_confirmations_now_cmd() -> None:
    from trading import TradingConfig, expire_confirmations
    cfg = TradingConfig.from_env()
    bot = _new_trading_bot()
    try:
        result = await expire_confirmations(
            config=cfg,
            confirm_path=CONFIRM_TRADES_FILE,
            live_path=LIVE_TRADES_FILE,
            journal_path=LIVE_TRADE_JOURNAL_FILE,
            send_dm=lambda t: _owner_dm(bot, t),
        )
        log.info("expire-confirmations: %s", result)
    finally:
        await bot.session.close()


async def run_live_reconcile_now_cmd() -> None:
    from trading import TradingConfig, live_reconcile
    cfg = TradingConfig.from_env()
    bot = _new_trading_bot()
    try:
        result = await live_reconcile(
            config=cfg,
            confirm_path=CONFIRM_TRADES_FILE,
            live_path=LIVE_TRADES_FILE,
            journal_path=LIVE_TRADE_JOURNAL_FILE,
            send_dm=lambda t: _owner_dm(bot, t),
        )
        log.info("live-reconcile: %s", _safe_log_dict(result))
    finally:
        await bot.session.close()


async def run_kill_switch_status_cmd() -> None:
    from trading import TradingConfig, kill_switch_status_text
    cfg = TradingConfig.from_env()
    text = await kill_switch_status_text(
        config=cfg,
        confirm_path=CONFIRM_TRADES_FILE,
        live_path=LIVE_TRADES_FILE,
        journal_path=LIVE_TRADE_JOURNAL_FILE,
    )
    print(text.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "").replace("<code>", "").replace("</code>", ""))
    if OWNER_CHAT_ID:
        bot = _new_trading_bot()
        try:
            await _owner_dm(bot, text)
        finally:
            await bot.session.close()


# ---------- Telegram callback handler (только в scheduler-режиме) ----------

def _register_confirm_callbacks(dp: Dispatcher) -> None:
    """Регистрирует обработчики кнопок ✅ Открыть / ❌ Отклонить.

    Принимает CallbackQuery только от OWNER_CHAT_ID. Идемпотентно: повторное
    нажатие после approve/reject/expire ничего не открывает второй раз
    (state-машина в ConfirmBroker.approve_trade проверяет статус).
    """
    from trading import TradingConfig, handle_approve, handle_reject

    async def _is_owner(cb: CallbackQuery) -> bool:
        if not OWNER_CHAT_ID:
            await cb.answer("Owner chat not configured", show_alert=True)
            return False
        if str(cb.from_user.id) != str(OWNER_CHAT_ID).lstrip("@"):
            log.warning("callback from non-owner user_id=%s; ignored", cb.from_user.id)
            await cb.answer("Not allowed", show_alert=True)
            return False
        return True

    @dp.callback_query(F.data.startswith("confirm_open:"))
    async def on_approve(cb: CallbackQuery):
        if not await _is_owner(cb):
            return
        await cb.answer("Обрабатываю approve…", show_alert=False)
        trade_id = cb.data.split(":", 1)[1]
        cfg = TradingConfig.from_env()
        try:
            result = await handle_approve(
                config=cfg,
                trade_id=trade_id,
                confirm_path=CONFIRM_TRADES_FILE,
                live_path=LIVE_TRADES_FILE,
                journal_path=LIVE_TRADE_JOURNAL_FILE,
                send_dm=lambda t: _owner_dm(cb.bot, t),
            )
            log.info("approve callback %s → %s", trade_id, _safe_log_dict(result))
        except Exception as e:
            log.exception("approve callback crashed: %s", e)
            try:
                await _owner_dm(cb.bot, f"<b>⚠️ [CONFIRM]</b> approve handler упал: {e}")
            except Exception:
                pass
        # снимаем кнопки с исходного сообщения, чтобы повторное нажатие не пыталось
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

    @dp.callback_query(F.data.startswith("confirm_reject:"))
    async def on_reject(cb: CallbackQuery):
        if not await _is_owner(cb):
            return
        await cb.answer("Отклонено.", show_alert=False)
        trade_id = cb.data.split(":", 1)[1]
        cfg = TradingConfig.from_env()
        try:
            result = await handle_reject(
                config=cfg,
                trade_id=trade_id,
                confirm_path=CONFIRM_TRADES_FILE,
                live_path=LIVE_TRADES_FILE,
                journal_path=LIVE_TRADE_JOURNAL_FILE,
                send_dm=lambda t: _owner_dm(cb.bot, t),
            )
            log.info("reject callback %s → %s", trade_id, _safe_log_dict(result))
        except Exception as e:
            log.exception("reject callback crashed: %s", e)
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass


# ---------- Stage 10: author-note review callbacks ----------

def _state_get_awaiting_author_edit() -> str:
    s = load_state()
    return str(s.get("awaiting_author_edit_for") or "")


def _state_set_awaiting_author_edit(draft_id: str | None) -> None:
    s = load_state()
    if draft_id:
        s["awaiting_author_edit_for"] = draft_id
    else:
        s.pop("awaiting_author_edit_for", None)
    save_state(s)


async def _handle_author_edit_feedback(bot: Bot, draft_id: str, feedback: str, *, cancel: bool) -> None:
    from author_notes import (
        AuthorNoteStore, ask_claude as author_ask_claude, get_rubric, build_html as author_build_html,
        review_keyboard as author_review_keyboard,
    )
    store = AuthorNoteStore(AUTHOR_NOTES_FILE)
    if cancel:
        _state_set_awaiting_author_edit(None)
        try:
            await bot.send_message(OWNER_CHAT_ID, "Правка author_note отменена.",
                                   parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return
    draft = store.get(draft_id)
    if not draft:
        _state_set_awaiting_author_edit(None)
        try:
            await bot.send_message(OWNER_CHAT_ID, "❌ Author-note не найден, правка отменена.",
                                   parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return
    if draft.status in ("published", "rejected"):
        _state_set_awaiting_author_edit(None)
        try:
            await bot.send_message(OWNER_CHAT_ID, f"⚠️ Author-note уже {draft.status}, правка отменена.",
                                   parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return
    if not CLAUDE_API_KEY:
        _state_set_awaiting_author_edit(None)
        try:
            await bot.send_message(OWNER_CHAT_ID, "❌ CLAUDE_API_KEY не задан, правка невозможна.",
                                   parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return

    try:
        await bot.send_message(OWNER_CHAT_ID, "✏️ Применяю правку author-note через Claude…",
                               parse_mode=ParseMode.HTML)
    except Exception:
        pass

    try:
        rubric = get_rubric(draft.rubric)
        claude = Anthropic(api_key=CLAUDE_API_KEY)
        payload = await asyncio.to_thread(
            lambda: author_ask_claude(
                claude, CLAUDE_MODEL, rubric,
                context=None, revise_feedback=feedback, previous_post_html=draft.post_html,
            )
        )
    except Exception as e:
        log.exception("author edit Claude crashed: %s", e)
        try:
            await bot.send_message(OWNER_CHAT_ID, f"❌ Правка упала: {html.escape(str(e), quote=False)}",
                                   parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return

    if not payload.get("ok"):
        try:
            await bot.send_message(
                OWNER_CHAT_ID,
                "⚠️ Claude вернул ошибку при правке: "
                + html.escape(str(payload.get("reason", "no reason")), quote=False),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    new_html = author_build_html(payload)
    draft.post_html = new_html
    draft.claude_json = payload
    draft.revision_count += 1
    draft.status = "revised"
    draft.owner_feedback.append(feedback)
    store.update(draft)
    _state_set_awaiting_author_edit(None)

    rubric = get_rubric(draft.rubric)
    head = (
        f"📝 <b>Author note — нужен ревью</b>\n"
        f"draft_id: <code>{html.escape(draft.draft_id, quote=False)}</code> | "
        f"рубрика: {html.escape(rubric.title, quote=False)} | rev: {draft.revision_count}\n"
        "──────────────"
    )
    try:
        await bot.send_message(
            OWNER_CHAT_ID, head + "\n\n" + new_html,
            parse_mode=ParseMode.HTML, disable_web_page_preview=True,
            reply_markup=_keyboard_from_dict(author_review_keyboard(draft.draft_id)),
        )
    except Exception as e:
        log.exception("author edit send preview failed: %s", e)


def _register_author_note_callbacks(dp: Dispatcher) -> None:
    """Stage 10: ✅ / ✏️ / ❌ для author_note. Без regenerate (см. ТЗ §9)."""
    from author_notes import (
        AuthorNoteStore, AuthorNoteConfig, get_rubric,
        review_keyboard as author_review_keyboard,
    )

    async def _is_owner_cb(cb: CallbackQuery) -> bool:
        if not OWNER_CHAT_ID:
            await cb.answer("Owner chat not configured", show_alert=True)
            return False
        if str(cb.from_user.id) != str(OWNER_CHAT_ID).lstrip("@"):
            log.warning("author callback from non-owner user_id=%s; ignored", cb.from_user.id)
            await cb.answer("Not allowed", show_alert=True)
            return False
        return True

    def _store() -> "AuthorNoteStore":
        return AuthorNoteStore(AUTHOR_NOTES_FILE)

    @dp.callback_query(F.data.startswith("author_publish:"))
    async def on_author_publish(cb: CallbackQuery):
        if not await _is_owner_cb(cb):
            return
        draft_id = cb.data.split(":", 1)[1]
        store = _store()
        existing = store.get(draft_id)
        if not existing:
            await cb.answer("Черновик не найден", show_alert=True)
            return
        if existing.status in ("publishing", "published", "rejected"):
            await cb.answer(f"Уже {existing.status}", show_alert=True)
            try:
                await cb.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            return
        cfg = AuthorNoteConfig.from_env()
        await cb.answer("Публикую…", show_alert=False)
        reasons: list[str] = []
        if cfg.author_note_dry_run:
            reasons.append("AUTHOR_NOTE_DRY_RUN=true. Публикация заблокирована.")
        if not CHANNEL_ID:
            reasons.append("CHANNEL_ID не задан в .env.")
        if reasons:
            try:
                await cb.bot.send_message(
                    OWNER_CHAT_ID,
                    "🚫 <b>Публикация заблокирована флагами</b>\n\n" + "\n".join(
                        f"• {html.escape(r, quote=False)}" for r in reasons
                    ),
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
            try:
                await cb.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            return

        draft = try_claim_for_publishing(store, draft_id)
        if draft is None:
            await cb.answer("Уже публикуется/обработано", show_alert=True)
            return

        try:
            await cb.bot.send_message(CHANNEL_ID, draft.post_html,
                                      parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except Exception as e:
            log.exception("author_publish send to channel failed: %s", e)
            release_claim(store, draft_id, new_status="pending_review")
            try:
                await cb.bot.send_message(OWNER_CHAT_ID,
                                          f"❌ Ошибка публикации: {html.escape(str(e), quote=False)}",
                                          parse_mode=ParseMode.HTML)
            except Exception:
                pass
            return

        draft.status = "published"
        store.update(draft)
        _state_increment_author_notes_week_count()
        try:
            _log_post_event(
                "author_note", published_to="channel",
                title=((draft.claude_json or {}).get("title") or draft.rubric or "")[:120],
                source="author_callback",
            )
        except Exception:
            pass
        try:
            await cb.bot.send_message(
                OWNER_CHAT_ID,
                f"✅ Author-note опубликован в {html.escape(CHANNEL_ID, quote=False)} "
                f"(draft_id: <code>{html.escape(draft.draft_id, quote=False)}</code>)",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

    @dp.callback_query(F.data.startswith("author_reject:"))
    async def on_author_reject(cb: CallbackQuery):
        if not await _is_owner_cb(cb):
            return
        draft_id = cb.data.split(":", 1)[1]
        store = _store()
        draft = store.get(draft_id)
        if not draft:
            await cb.answer("Черновик не найден", show_alert=True)
            return
        if draft.status in ("published", "rejected"):
            await cb.answer(f"Уже {draft.status}", show_alert=True)
            try:
                await cb.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            return
        draft.status = "rejected"
        store.update(draft)
        await cb.answer("Отклонено.", show_alert=False)
        try:
            await cb.bot.send_message(
                OWNER_CHAT_ID,
                f"❌ Author-note отклонён (draft_id: <code>{html.escape(draft.draft_id, quote=False)}</code>).",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

    @dp.callback_query(F.data.startswith("author_edit:"))
    async def on_author_edit(cb: CallbackQuery):
        if not await _is_owner_cb(cb):
            return
        draft_id = cb.data.split(":", 1)[1]
        store = _store()
        draft = store.get(draft_id)
        if not draft:
            await cb.answer("Черновик не найден", show_alert=True)
            return
        if draft.status in ("published", "rejected"):
            await cb.answer(f"Уже {draft.status}", show_alert=True)
            return
        _state_set_awaiting_author_edit(draft_id)
        await cb.answer("Жду текст правки в следующем сообщении.", show_alert=False)
        try:
            rubric = get_rubric(draft.rubric)
            await cb.bot.send_message(
                OWNER_CHAT_ID,
                "✏️ <b>Жду правку author_note</b>\n\n"
                f"draft_id: <code>{html.escape(draft.draft_id, quote=False)}</code>\n"
                f"рубрика: {html.escape(rubric.title, quote=False)}\n\n"
                "Напиши, что исправить. Например: «сделай теплее», «убери сарказм», "
                "«добавь самоиронии».\n\n"
                "Чтобы отменить — отправь <code>cancel</code>.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


# ---------- Stage 13: weekly_diary review callbacks ----------

def _register_weekly_diary_callbacks(dp: Dispatcher) -> None:
    """Stage 13: ✅ / ❌ для weekly_diary. Без regenerate/edit — отклонил и
    перезапусти `python bot.py --weekly-now`."""
    from weekly_diary import WeeklyDiaryStore

    async def _is_owner_cb(cb: CallbackQuery) -> bool:
        if not OWNER_CHAT_ID:
            await cb.answer("Owner chat not configured", show_alert=True)
            return False
        if str(cb.from_user.id) != str(OWNER_CHAT_ID).lstrip("@"):
            log.warning("weekly callback from non-owner user_id=%s; ignored", cb.from_user.id)
            await cb.answer("Not allowed", show_alert=True)
            return False
        return True

    def _store() -> "WeeklyDiaryStore":
        return WeeklyDiaryStore(WEEKLY_DIARY_FILE)

    @dp.callback_query(F.data.startswith("weekly_publish:"))
    async def on_weekly_publish(cb: CallbackQuery):
        if not await _is_owner_cb(cb):
            return
        draft_id = cb.data.split(":", 1)[1]
        store = _store()
        existing = store.get(draft_id)
        if not existing:
            await cb.answer("Черновик не найден", show_alert=True)
            return
        if existing.status in ("publishing", "published", "rejected"):
            await cb.answer(f"Уже {existing.status}", show_alert=True)
            try:
                await cb.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            return
        from weekly_diary import WeeklyDiaryConfig
        cfg = WeeklyDiaryConfig.from_env()
        await cb.answer("Публикую…", show_alert=False)
        reasons: list[str] = []
        if cfg.weekly_diary_dry_run:
            reasons.append("WEEKLY_DIARY_DRY_RUN=true. Публикация заблокирована.")
        if not CHANNEL_ID:
            reasons.append("CHANNEL_ID не задан в .env.")
        if reasons:
            try:
                await cb.bot.send_message(
                    OWNER_CHAT_ID,
                    "🚫 <b>Публикация заблокирована флагами</b>\n\n" + "\n".join(
                        f"• {html.escape(r, quote=False)}" for r in reasons
                    ),
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
            try:
                await cb.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            return

        draft = try_claim_for_publishing(store, draft_id)
        if draft is None:
            await cb.answer("Уже публикуется/обработано", show_alert=True)
            return

        try:
            await cb.bot.send_message(CHANNEL_ID, draft.post_html,
                                      parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        except Exception as e:
            log.exception("weekly_publish send to channel failed: %s", e)
            release_claim(store, draft_id, new_status="pending_review")
            try:
                await cb.bot.send_message(OWNER_CHAT_ID,
                                          f"❌ Ошибка публикации: {html.escape(str(e), quote=False)}",
                                          parse_mode=ParseMode.HTML)
            except Exception:
                pass
            return

        draft.status = "published"
        store.update(draft)
        try:
            _log_post_event(
                "weekly_diary", published_to="channel",
                title=((draft.claude_json or {}).get("title") or "Дневник недели")[:120],
                source="weekly_callback",
            )
        except Exception:
            pass
        try:
            await cb.bot.send_message(
                OWNER_CHAT_ID,
                f"✅ Weekly diary опубликован в {html.escape(CHANNEL_ID, quote=False)} "
                f"(draft_id: <code>{html.escape(draft.draft_id, quote=False)}</code>)",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

    @dp.callback_query(F.data.startswith("weekly_reject:"))
    async def on_weekly_reject(cb: CallbackQuery):
        if not await _is_owner_cb(cb):
            return
        draft_id = cb.data.split(":", 1)[1]
        store = _store()
        draft = store.get(draft_id)
        if not draft:
            await cb.answer("Черновик не найден", show_alert=True)
            return
        if draft.status in ("published", "rejected"):
            await cb.answer(f"Уже {draft.status}", show_alert=True)
            try:
                await cb.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            return
        draft.status = "rejected"
        store.update(draft)
        await cb.answer("Отклонено.", show_alert=False)
        try:
            await cb.bot.send_message(
                OWNER_CHAT_ID,
                f"❌ Weekly diary отклонён (draft_id: <code>{html.escape(draft.draft_id, quote=False)}</code>).",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass


# ---------- Stage 6b: news review callbacks ----------

def _state_get_awaiting_news_edit() -> str:
    s = load_state()
    return str(s.get("awaiting_news_edit_for") or "")


def _state_set_awaiting_news_edit(draft_id: str | None) -> None:
    s = load_state()
    if draft_id:
        s["awaiting_news_edit_for"] = draft_id
    else:
        s.pop("awaiting_news_edit_for", None)
    save_state(s)


def _state_get_news_post_counter() -> int:
    """Stage 14 — счётчик опубликованных в канал news-постов (для mistake_theme inject)."""
    s = load_state()
    try:
        return int(s.get("news_post_counter") or 0)
    except (TypeError, ValueError):
        return 0


def _state_inc_news_post_counter() -> int:
    """Stage 14 — atomic increment, возвращает новое значение."""
    s = load_state()
    cur = int(s.get("news_post_counter") or 0)
    s["news_post_counter"] = cur + 1
    save_state(s)
    return cur + 1


# Stage 12e — image-intent triggers, разделённые на два класса:
# AI-intent → вызвать OpenAI (через news_generate_ai_image),
# source-intent → вытащить og:image из источника (через news_refresh_source_image).
# Default: AI-намерение требует явных слов «сгенери» / «нарисуй» / «AI-картинка».
# Source-намерение: «возьми из источника», «обнови превью», «og image».

_AI_IMAGE_PATTERNS = (
    "сгенери",                  # сгенери / сгенерируй
    "нарисуй",
    "сделай ai-картин",
    "сделай ии-картин",
    "сделай arт",
    "сделай арт",
    "новая ai",
    "новую ai",
    "ai-картин",
    "ии-картин",
    "ai картин",
    "ии картин",
    "тематичес",                # «сгенерируй тематическое изображение»
    "перерисуй картин",
    "перегенери картин",
    "regenerate image",
    "generate image",
    "new image",
    "another image",
    "🖼",
)

_SOURCE_IMAGE_PATTERNS = (
    "из источника",             # «возьми картинку из источника»
    "превью источника",
    "обнови превью",
    "обнови картин",            # «обнови картинку из источника»
    "source image",
    "og image",
    "og:image",
    "twitter:image",
    "🔄",
)


def _looks_like_ai_image_request(text: str) -> bool:
    s = (text or "").strip().lower()
    if not s or len(s) > 80:
        return False
    if "ai" in s and ("картин" in s or "изображ" in s):
        return True
    if any(p in s for p in _AI_IMAGE_PATTERNS):
        return True
    # «сделай картинку», «новую картинку» — без префикса AI считаются AI (legacy backward-compat),
    # но только если нет явного source-маркера в той же фразе.
    if "из источник" in s or "source" in s or "og:" in s:
        return False
    if "картин" in s and ("сгенери" in s or "нарисуй" in s or "сделай" in s
                          or "новая" in s or "новую" in s or "перерисуй" in s):
        return True
    if "изображ" in s and ("сгенери" in s or "нарисуй" in s or "сделай" in s
                           or "новое" in s or "перерисуй" in s):
        return True
    return False


def _looks_like_source_image_request(text: str) -> bool:
    s = (text or "").strip().lower()
    if not s or len(s) > 80:
        return False
    return any(p in s for p in _SOURCE_IMAGE_PATTERNS)


# legacy alias — оставлен на случай если в коде ещё есть вызовы; делегирует к AI-варианту
def _looks_like_image_request(text: str) -> bool:
    return _looks_like_ai_image_request(text) or _looks_like_source_image_request(text)


def _rebuild_draft_post_html(draft) -> None:
    """Stage 12f — пересобрать draft.post_html в зависимости от image_path.

    Если у draft есть картинка → compact-формат (умещается в caption ≤ 1024).
    Если нет → полный формат. Вызывается после любого изменения image_path или claude_json.
    """
    try:
        from news import NewsItem, build_news_html
        sn = draft.source_news or {}
        item = NewsItem(
            title=sn.get("title") or "",
            url=sn.get("url") or "",
            source=sn.get("source") or "",
            published_at=sn.get("published_at") or "",
            summary=sn.get("summary") or "",
            assets=list(sn.get("assets") or []),
            category=sn.get("category") or "other",
            sector=sn.get("sector") or "other",
            impact_score=float(sn.get("impact_score") or 0.0),
        )
        draft.post_html = build_news_html(
            draft.claude_json or {},
            item,
            compact=bool(getattr(draft, "image_path", "")),
        )
    except Exception as e:
        log.warning("rebuild draft.post_html failed: %s", e)


async def _handle_news_ai_image_text_request(bot: Bot, draft) -> None:
    """Stage 12e — текстовый аналог кнопки 🖼 «Сгенерировать AI-картинку».

    Единственный текстовый путь к OpenAI Image API. Делает: drop кэша по news_hash,
    генерация, обновление draft (image_path/origin/prompt/model/created_at), preview.
    """
    if not OPENAI_API_KEY:
        try:
            await bot.send_message(
                OWNER_CHAT_ID,
                "❌ OPENAI_API_KEY не задан — AI-картинка невозможна.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    try:
        await bot.send_message(OWNER_CHAT_ID, "🖼 Генерирую AI-картинку…")
    except Exception:
        pass

    from news import NewsItem, news_hash, image_prompt_for, DraftStore
    sn = draft.source_news
    item = NewsItem(
        title=sn.get("title") or "",
        url=sn.get("url") or "",
        source=sn.get("source") or "",
        published_at=sn.get("published_at") or "",
        summary=sn.get("summary") or "",
        assets=list(sn.get("assets") or []),
        category=sn.get("category") or "other",
        sector=sn.get("sector") or "other",
        impact_score=float(sn.get("impact_score") or 0.0),
    )

    cache_path = _news_image_path_for_hash(news_hash(item))
    if cache_path.exists():
        try:
            cache_path.unlink()
        except Exception:
            pass

    try:
        img_path = await _news_image_provider(item, draft.claude_json or {})
    except Exception as e:
        log.exception("news AI-image text request crashed: %s", e)
        try:
            await bot.send_message(
                OWNER_CHAT_ID,
                f"❌ Генерация упала: {html.escape(str(e), quote=False)}",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    if not img_path:
        try:
            await bot.send_message(
                OWNER_CHAT_ID,
                "⚠️ Не удалось сгенерировать AI-картинку. Попробуй ещё раз или опубликуй без картинки.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    store = DraftStore(NEWS_DRAFTS_FILE)
    draft.image_path = img_path
    draft.image_origin = "generated_ai"
    draft.image_source_url = ""
    draft.image_prompt = (image_prompt_for(item, (draft.claude_json or {}).get("image_prompt_hint") or ""))[:500]
    draft.image_model = "openai-image"
    draft.image_created_at = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
    _rebuild_draft_post_html(draft)
    store.update(draft)

    await _resend_preview_with_image(bot, draft, img_path, item, header_label="Превью с новой AI-картинкой")


async def _handle_news_source_image_text_request(bot: Bot, draft) -> None:
    """Stage 12e — текстовый аналог кнопки 🔄 «Обновить превью источника». Без OpenAI."""
    try:
        await bot.send_message(OWNER_CHAT_ID, "🔄 Тяну превью источника…")
    except Exception:
        pass

    from news import NewsItem, NewsSourceImageExtractor, DraftStore, NewsConfig
    sn = draft.source_news
    item = NewsItem(
        title=sn.get("title") or "",
        url=sn.get("url") or "",
        source=sn.get("source") or "",
        published_at=sn.get("published_at") or "",
        summary=sn.get("summary") or "",
        assets=list(sn.get("assets") or []),
        category=sn.get("category") or "other",
        sector=sn.get("sector") or "other",
        impact_score=float(sn.get("impact_score") or 0.0),
    )

    try:
        ncfg = NewsConfig.from_env()
        extractor = NewsSourceImageExtractor(Path(ncfg.news_source_image_save_dir))
        local_path, src_url = await asyncio.to_thread(extractor.get_source_image, item)
    except Exception as e:
        log.exception("news source-image text request crashed: %s", e)
        try:
            await bot.send_message(
                OWNER_CHAT_ID,
                f"❌ Source image fetch упал: {html.escape(str(e), quote=False)}",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    if not local_path:
        try:
            await bot.send_message(
                OWNER_CHAT_ID,
                "⚠️ В источнике не нашлось og:image / twitter:image / article:image. "
                "Можно нажать 🖼 «Сгенерировать AI-картинку».",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    store = DraftStore(NEWS_DRAFTS_FILE)
    draft.image_path = local_path
    draft.image_origin = "source_preview"
    draft.image_source_url = src_url or ""
    draft.image_credit = item.source or ""
    draft.image_prompt = ""
    draft.image_model = ""
    draft.image_created_at = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
    _rebuild_draft_post_html(draft)
    store.update(draft)

    await _resend_preview_with_image(bot, draft, local_path, item, header_label="Превью с картинкой источника")


async def _resend_preview_with_image(
    bot: Bot,
    draft,
    img_path: str,
    item,
    *,
    header_label: str = "Превью",
) -> None:
    """Общий хвост для AI/source текстовых хендлеров: рендерим превью с новым изображением."""
    from news import validate_payload_for_publish, review_keyboard
    sn = draft.source_news
    sector = html.escape(sn.get("sector") or "-", quote=False)
    impact = int(sn.get("impact_score") or 0)
    try:
        guard = validate_payload_for_publish(draft.claude_json or {}, item)
    except Exception:
        guard = []
    origin_label = {
        "generated_ai":   "🖼 AI",
        "source_preview": "📰 источник",
        "manual_upload":  "📎 вручную",
        "none":           "—",
    }.get(getattr(draft, "image_origin", "none"), "—")
    head_lines = [
        f"🧪 <b>{html.escape(header_label, quote=False)}</b>",
        f"draft_id: <code>{html.escape(draft.draft_id, quote=False)}</code> | "
        f"sector: {sector} | impact: {impact} | rev: {draft.revision_count}",
        f"image: <code>{html.escape(Path(img_path).name, quote=False)}</code> ({origin_label})",
    ]
    if getattr(draft, "image_source_url", ""):
        head_lines.append(
            f"src: <code>{html.escape(draft.image_source_url, quote=False)[:90]}</code>"
        )
    if guard:
        head_lines.append("")
        head_lines.append("🚫 <b>Publish-guard:</b>")
        for r in guard[:6]:
            head_lines.append(f"• {html.escape(r, quote=False)}")
        head_lines.append("Исправь правкой ✏️ / перегенерь 🔁 — потом ✅.")
    head_lines.append("──────────────")
    head = "\n".join(head_lines)

    await send_post_with_optional_image(
        bot, OWNER_CHAT_ID,
        head + "\n\n" + draft.post_html,
        img_path,
        reply_markup=_keyboard_from_dict(review_keyboard(draft.draft_id)),
    )


def _publish_guard_reasons() -> list[str]:
    """Возвращает причины, по которым публикация в канал ЗАБЛОКИРОВАНА. Пусто = можно публиковать."""
    reasons = []
    if DRY_RUN:
        reasons.append("DRY_RUN=true. Публикация заблокирована. Для публикации поставь DRY_RUN=false.")
    try:
        from news import NewsConfig
        ncfg = NewsConfig.from_env()
        if not ncfg.news_publish_to_channel:
            reasons.append("NEWS_PUBLISH_TO_CHANNEL=false. Публикация новостей в канал выключена.")
        if not ncfg.enable_news:
            reasons.append("ENABLE_NEWS=false. Новостной модуль выключен.")
    except Exception as e:
        reasons.append(f"NewsConfig load failed: {e}")
    if not CHANNEL_ID:
        reasons.append("CHANNEL_ID не задан в .env.")
    return reasons


def _register_news_callbacks(dp: Dispatcher) -> None:
    """Stage 6b: ✅ Опубликовать / ✏️ Исправить / 🔁 Перегенерировать / ❌ Отклонить.

    Все callback-и принимаются только от OWNER_CHAT_ID. После approve/reject/regen
    кнопки снимаются с исходного сообщения, чтобы повторное нажатие не дублировало
    действие. Edit-flow ждёт следующее текстовое сообщение от владельца.
    """
    from news import (
        NewsConfig, DraftStore, regenerate_payload, revise_payload,
        review_keyboard, build_news_html,
    )

    async def _is_owner_cb(cb: CallbackQuery) -> bool:
        if not OWNER_CHAT_ID:
            await cb.answer("Owner chat not configured", show_alert=True)
            return False
        if str(cb.from_user.id) != str(OWNER_CHAT_ID).lstrip("@"):
            log.warning("news callback from non-owner user_id=%s; ignored", cb.from_user.id)
            await cb.answer("Not allowed", show_alert=True)
            return False
        return True

    def _store() -> "DraftStore":
        return DraftStore(NEWS_DRAFTS_FILE)

    async def _send_dm_html(bot: Bot, text: str) -> None:
        await bot.send_message(
            OWNER_CHAT_ID, text,
            parse_mode=ParseMode.HTML, disable_web_page_preview=True,
        )

    async def _send_preview(bot: Bot, draft) -> None:
        """Stage 14: превью владельцу = header сообщение + (опц.guard) + сам пост.

        Сам пост идёт точно так, как пошёл бы в канал — фото+caption или text-only.
        Header не вмешивается в HTML поста чтобы не превышать caption-лимит 1024.
        """
        from news import NewsItem, validate_payload_for_publish, validate_payload_v2
        sn = draft.source_news or {}
        sector = html.escape(sn.get("sector") or "-", quote=False)
        impact = int(sn.get("impact_score") or 0)
        cj = draft.claude_json or {}
        schema_version = getattr(draft, "schema_version", "v1")
        tone = str(cj.get("tone") or "-")
        try:
            _item = NewsItem(
                title=sn.get("title") or "",
                url=sn.get("url") or "",
                source=sn.get("source") or "",
                published_at=sn.get("published_at") or "",
                summary=sn.get("summary") or "",
                assets=list(sn.get("assets") or []),
                category=sn.get("category") or "other",
                sector=sn.get("sector") or "other",
                impact_score=float(sn.get("impact_score") or 0.0),
            )
            if schema_version == "v2":
                guard = validate_payload_v2(cj, _item)
            else:
                guard = validate_payload_for_publish(cj, _item)
        except Exception:
            guard = []

        # 1) Header — отдельное мини-сообщение
        header = (
            f"🧪 Превью #<code>{html.escape(draft.draft_id[:8], quote=False)}</code> · "
            f"sector={sector} · impact={impact} · "
            f"tone={html.escape(tone, quote=False)} · rev={draft.revision_count}"
        )
        if draft.image_path:
            header += f"\n🖼 {html.escape(Path(draft.image_path).name, quote=False)}"
        try:
            await bot.send_message(
                OWNER_CHAT_ID, header,
                parse_mode=ParseMode.HTML, disable_web_page_preview=True,
            )
        except Exception as e:
            log.warning("_send_preview header failed: %s", e)

        # 2) (опц.) guard reasons
        if guard:
            guard_text = "🚫 <b>Publish-guard:</b>\n" + "\n".join(
                f"• {html.escape(r, quote=False)}" for r in guard[:6]
            ) + "\nИсправь правкой ✏️ / перегенерь 🔁 / 🖼 — потом ✅."
            try:
                await bot.send_message(
                    OWNER_CHAT_ID, guard_text,
                    parse_mode=ParseMode.HTML, disable_web_page_preview=True,
                )
            except Exception as e:
                log.warning("_send_preview guard failed: %s", e)

        # 3) Сам пост — как в канал, с кнопками
        await send_post_with_optional_image(
            bot, OWNER_CHAT_ID,
            draft.post_html,
            draft.image_path or None,
            title=str(cj.get("specific_title") or ""),
            brief=str(cj.get("brief_review") or cj.get("short_summary") or ""),
            reply_markup=_keyboard_from_dict(review_keyboard(draft.draft_id)),
        )

    @dp.callback_query(F.data.startswith("news_publish:"))
    async def on_news_publish(cb: CallbackQuery):
        log.info(
            "CB news_publish: from=%s data=%s msg_id=%s",
            cb.from_user.id if cb.from_user else "?",
            cb.data,
            cb.message.message_id if cb.message else "?",
        )
        await cb.answer()  # Stage 14: ack СРАЗУ, до тяжёлой логики
        if not await _is_owner_cb(cb):
            log.warning(
                "CB news_publish: not owner (from=%s expected=%s)",
                cb.from_user.id if cb.from_user else "?",
                OWNER_CHAT_ID,
            )
            return
        draft_id = cb.data.split(":", 1)[1]
        store = _store()
        draft = store.get(draft_id)
        if not draft:
            await cb.answer("Черновик не найден", show_alert=True)
            return
        # Stage 14 idempotency: расширенный TERMINAL включая publishing
        TERMINAL = {"published", "rejected", "publishing"}
        if draft.status in TERMINAL:
            await cb.answer(f"Уже обработано ({draft.status})", show_alert=True)
            try:
                await cb.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            return

        # Stage 14: переводим в publishing СРАЗУ, чтобы второй клик увидел terminal
        draft.status = "publishing"
        store.update(draft)

        reasons = _publish_guard_reasons()
        if reasons:
            draft.status = "approved"
            store.update(draft)
            try:
                await _send_dm_html(
                    cb.bot,
                    "🚫 <b>Публикация заблокирована флагами</b>\n\n" + "\n".join(
                        f"• {html.escape(r, quote=False)}" for r in reasons
                    ),
                )
            except Exception as e:
                log.warning("send block-reason DM failed: %s", e)
            try:
                await cb.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            return

        # Stage 12b P0.4 — payload-level publish-guard (specific_title, key_points,
        # why_it_matters, brief_review и т.д.). Если что-то пустое или generic —
        # не публикуем, а просим владельца исправить.
        try:
            from news import validate_payload_for_publish, NewsItem as _NI
            sn = draft.source_news or {}
            _item_for_guard = _NI(
                title=sn.get("title") or "",
                url=sn.get("url") or "",
                source=sn.get("source") or "",
                published_at=sn.get("published_at") or "",
                summary=sn.get("summary") or "",
                assets=list(sn.get("assets") or []),
                category=sn.get("category") or "other",
                sector=sn.get("sector") or "other",
                impact_score=float(sn.get("impact_score") or 0.0),
            )
            payload_reasons = validate_payload_for_publish(draft.claude_json or {}, _item_for_guard)
        except Exception as e:
            payload_reasons = [f"publish-guard crashed: {e}"]

        if payload_reasons:
            # Откат статуса — владелец будет править/регенерировать
            draft.status = "pending_review"
            store.update(draft)
            try:
                await _send_dm_html(
                    cb.bot,
                    "🚫 <b>Publish-guard заблокировал публикацию</b>\n\n"
                    + "\n".join(f"• {html.escape(r, quote=False)}" for r in payload_reasons[:8])
                    + "\n\nИсправь правкой ✏️ или перегенерь 🔁 — после этого можно ✅.",
                )
            except Exception:
                pass
            # кнопки оставляем — владелец доделает и нажмёт ещё раз
            return

        try:
            cj = draft.claude_json or {}
            await send_post_with_optional_image(
                cb.bot, CHANNEL_ID, draft.post_html,
                draft.image_path or None,
                title=str(cj.get("specific_title") or ""),
                brief=str(cj.get("brief_review") or cj.get("short_summary") or ""),
                reply_markup=None,
            )
        except Exception as e:
            log.exception("news_publish: send to channel failed: %s", e)
            # Stage 14: откат idempotency — позволяем владельцу повторить
            draft.status = "pending_review"
            store.update(draft)
            try:
                await _send_dm_html(cb.bot, f"❌ Ошибка публикации в канал: {html.escape(str(e), quote=False)}")
            except Exception:
                pass
            return

        draft.status = "published"
        store.update(draft)

        # Stage 14: инкрементируем news_post_counter в state.json
        try:
            _state_inc_news_post_counter()
        except Exception as e:
            log.warning("news_post_counter inc failed: %s", e)

        # отметим в news_history.json (для дедупа и счётчика postedToday)
        try:
            from news import NewsDeduplicator, NewsItem
            dedup = NewsDeduplicator(NEWS_HISTORY_FILE)
            sn = draft.source_news
            item = NewsItem(
                title=sn.get("title") or "",
                url=sn.get("url") or "",
                source=sn.get("source") or "",
                published_at=sn.get("published_at") or "",
                summary=sn.get("summary") or "",
                assets=list(sn.get("assets") or []),
                category=sn.get("category") or "other",
                sector=sn.get("sector") or "other",
                impact_score=float(sn.get("impact_score") or 0.0),
            )
            short = (draft.claude_json.get("short_summary") or "").strip() if isinstance(draft.claude_json, dict) else ""
            dedup.remember(item, "published_channel", short_summary=short)
        except Exception as e:
            log.warning("news_publish: history.remember failed: %s", e)
        # Stage 10+: учёт в контент-миксе. post_type — sector выбранной новости
        # (ai_crypto / scam_radar / political_market_noise / ...), category свернётся в "news".
        try:
            sn = draft.source_news or {}
            _log_post_event(
                sn.get("sector") or "news",
                published_to="channel",
                title=(sn.get("title") or "")[:120],
                source="news_callback",
            )
        except Exception:
            pass

        try:
            await _send_dm_html(
                cb.bot,
                f"✅ Опубликовано в {html.escape(CHANNEL_ID, quote=False)} "
                f"(draft_id: <code>{html.escape(draft.draft_id, quote=False)}</code>)",
            )
        except Exception:
            pass
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

    @dp.callback_query(F.data.startswith("news_reject:"))
    async def on_news_reject(cb: CallbackQuery):
        log.info(
            "CB news_reject: from=%s data=%s",
            cb.from_user.id if cb.from_user else "?", cb.data,
        )
        await cb.answer()
        if not await _is_owner_cb(cb):
            log.warning("CB news_reject: not owner")
            return
        draft_id = cb.data.split(":", 1)[1]
        store = _store()
        draft = store.get(draft_id)
        if not draft:
            await cb.answer("Черновик не найден", show_alert=True)
            return
        TERMINAL = {"published", "rejected", "publishing"}
        if draft.status in TERMINAL:
            await cb.answer(f"Уже обработано ({draft.status})", show_alert=True)
            try:
                await cb.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            return
        draft.status = "rejected"
        store.update(draft)

        # пометим в news_history.json чтобы дедуп не предлагал её снова
        try:
            from news import NewsDeduplicator, NewsItem
            dedup = NewsDeduplicator(NEWS_HISTORY_FILE)
            sn = draft.source_news
            item = NewsItem(
                title=sn.get("title") or "",
                url=sn.get("url") or "",
                source=sn.get("source") or "",
                published_at=sn.get("published_at") or "",
                summary=sn.get("summary") or "",
                assets=list(sn.get("assets") or []),
                category=sn.get("category") or "other",
                sector=sn.get("sector") or "other",
                impact_score=float(sn.get("impact_score") or 0.0),
            )
            dedup.remember(item, "rejected_by_owner", short_summary="rejected by owner")
        except Exception as e:
            log.warning("news_reject: history.remember failed: %s", e)

        await cb.answer("Отклонено.", show_alert=False)
        try:
            await _send_dm_html(cb.bot, f"❌ Новость отклонена (draft_id: <code>{html.escape(draft.draft_id, quote=False)}</code>).")
        except Exception:
            pass
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

    @dp.callback_query(F.data.startswith("news_regenerate:"))
    async def on_news_regenerate(cb: CallbackQuery):
        log.info(
            "CB news_regenerate: from=%s data=%s",
            cb.from_user.id if cb.from_user else "?", cb.data,
        )
        await cb.answer()
        if not await _is_owner_cb(cb):
            log.warning("CB news_regenerate: not owner")
            return
        draft_id = cb.data.split(":", 1)[1]
        store = _store()
        draft = store.get(draft_id)
        if not draft:
            await cb.answer("Черновик не найден", show_alert=True)
            return
        if draft.status in ("published", "rejected", "publishing"):
            await cb.answer(f"Уже обработано ({draft.status})", show_alert=True)
            return
        if not CLAUDE_API_KEY:
            await cb.answer("CLAUDE_API_KEY не задан", show_alert=True)
            return

        await cb.answer("Перегенерирую через Claude…", show_alert=False)
        try:
            ncfg = NewsConfig.from_env()
            claude = Anthropic(api_key=CLAUDE_API_KEY)
            payload = await asyncio.to_thread(
                regenerate_payload, draft, ncfg, claude, CLAUDE_MODEL,
            )
        except Exception as e:
            log.exception("news_regenerate Claude crashed: %s", e)
            try:
                await _send_dm_html(cb.bot, f"❌ Перегенерация упала: {html.escape(str(e), quote=False)}")
            except Exception:
                pass
            return

        if not payload.get("should_publish"):
            try:
                await _send_dm_html(
                    cb.bot,
                    "⚠️ Claude вернул should_publish=false при перегенерации: "
                    + html.escape(str(payload.get("reason", "no reason")), quote=False),
                )
            except Exception:
                pass
            return

        from news.publisher import build_html as _build_html
        from news import NewsItem
        sn = draft.source_news
        item_for_render = NewsItem(
            title=sn.get("title") or "",
            url=sn.get("url") or "",
            source=sn.get("source") or "",
            published_at=sn.get("published_at") or "",
            summary=sn.get("summary") or "",
            assets=list(sn.get("assets") or []),
            category=sn.get("category") or "other",
            sector=sn.get("sector") or "other",
            impact_score=float(sn.get("impact_score") or 0.0),
        )
        # Stage 12f — compact если у draft уже стоит картинка (revise/regenerate
        # сохраняют image), иначе full-format.
        new_html = _build_html(payload, item_for_render, compact=bool(getattr(draft, "image_path", "")))
        draft.post_html = new_html
        draft.claude_json = payload
        draft.revision_count += 1
        draft.status = "revised"
        store.update(draft)

        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        try:
            await _send_preview(cb.bot, draft)
        except Exception as e:
            log.exception("news_regenerate: send preview failed: %s", e)

    async def _build_news_item_from_draft(draft):
        """Восстановить NewsItem из draft.source_news для downstream-операций."""
        from news import NewsItem
        sn = draft.source_news or {}
        return NewsItem(
            title=sn.get("title") or "",
            url=sn.get("url") or "",
            source=sn.get("source") or "",
            published_at=sn.get("published_at") or "",
            summary=sn.get("summary") or "",
            assets=list(sn.get("assets") or []),
            category=sn.get("category") or "other",
            sector=sn.get("sector") or "other",
            impact_score=float(sn.get("impact_score") or 0.0),
        )

    @dp.callback_query(F.data.startswith("news_generate_ai_image:"))
    async def on_news_generate_ai_image(cb: CallbackQuery):
        """Stage 12e — единственная кнопка, вызывающая OpenAI Image API."""
        log.info(
            "CB news_generate_ai_image: from=%s data=%s",
            cb.from_user.id if cb.from_user else "?", cb.data,
        )
        await cb.answer()
        if not await _is_owner_cb(cb):
            log.warning("CB news_generate_ai_image: not owner")
            return
        draft_id = cb.data.split(":", 1)[1]
        store = _store()
        draft = store.get(draft_id)
        if not draft:
            await cb.answer("Черновик не найден", show_alert=True)
            return
        if draft.status in ("published", "rejected"):
            await cb.answer(f"Уже {draft.status}", show_alert=True)
            return
        if not OPENAI_API_KEY:
            await cb.answer("OPENAI_API_KEY не задан", show_alert=True)
            return

        await cb.answer("Генерирую AI-картинку…", show_alert=False)
        try:
            item_for_img = await _build_news_item_from_draft(draft)
            from news import news_hash, image_prompt_for
            cache_path = _news_image_path_for_hash(news_hash(item_for_img))
            if cache_path.exists():
                try:
                    cache_path.unlink()
                except Exception:
                    pass
            img_path = await _news_image_provider(item_for_img, draft.claude_json or {})
        except Exception as e:
            log.exception("news_generate_ai_image crashed: %s", e)
            try:
                await _send_dm_html(cb.bot, f"❌ Генерация картинки упала: {html.escape(str(e), quote=False)}")
            except Exception:
                pass
            return

        if not img_path:
            try:
                await _send_dm_html(
                    cb.bot,
                    "⚠️ Не удалось сгенерировать AI-картинку (OpenAI вернул пусто или упал). "
                    "Попробуй ещё раз или опубликуй без картинки.",
                )
            except Exception:
                pass
            return

        draft.image_path = img_path
        draft.image_origin = "generated_ai"
        draft.image_source_url = ""
        draft.image_prompt = (image_prompt_for(item_for_img, (draft.claude_json or {}).get("image_prompt_hint") or ""))[:500]
        draft.image_model = "openai-image"
        draft.image_created_at = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
        _rebuild_draft_post_html(draft)
        store.update(draft)
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        try:
            await _send_preview(cb.bot, draft)
        except Exception as e:
            log.exception("news_generate_ai_image: send preview failed: %s", e)

    @dp.callback_query(F.data.startswith("news_refresh_source_image:"))
    async def on_news_refresh_source_image(cb: CallbackQuery):
        """Stage 12e — заново вытащить og:image / twitter:image из источника."""
        log.info(
            "CB news_refresh_source_image: from=%s data=%s",
            cb.from_user.id if cb.from_user else "?", cb.data,
        )
        await cb.answer()
        if not await _is_owner_cb(cb):
            log.warning("CB news_refresh_source_image: not owner")
            return
        draft_id = cb.data.split(":", 1)[1]
        store = _store()
        draft = store.get(draft_id)
        if not draft:
            await cb.answer("Черновик не найден", show_alert=True)
            return
        if draft.status in ("published", "rejected"):
            await cb.answer(f"Уже {draft.status}", show_alert=True)
            return

        await cb.answer("Тяну превью источника…", show_alert=False)
        item_for_img = await _build_news_item_from_draft(draft)
        try:
            ncfg = NewsConfig.from_env()
            from news import NewsSourceImageExtractor
            extractor = NewsSourceImageExtractor(Path(ncfg.news_source_image_save_dir))
            local_path, src_url = await asyncio.to_thread(extractor.get_source_image, item_for_img)
        except Exception as e:
            log.exception("news_refresh_source_image crashed: %s", e)
            try:
                await _send_dm_html(cb.bot, f"❌ Source image fetch упал: {html.escape(str(e), quote=False)}")
            except Exception:
                pass
            return

        if not local_path:
            try:
                await _send_dm_html(
                    cb.bot,
                    "⚠️ В источнике не нашлось og:image / twitter:image / article:image. "
                    "Можно нажать 🖼 «Сгенерировать AI-картинку».",
                )
            except Exception:
                pass
            return

        draft.image_path = local_path
        draft.image_origin = "source_preview"
        draft.image_source_url = src_url or ""
        draft.image_credit = item_for_img.source or ""
        draft.image_prompt = ""
        draft.image_model = ""
        draft.image_created_at = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
        _rebuild_draft_post_html(draft)
        store.update(draft)
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        try:
            await _send_preview(cb.bot, draft)
        except Exception as e:
            log.exception("news_refresh_source_image: send preview failed: %s", e)

    @dp.callback_query(F.data.startswith("news_edit:"))
    async def on_news_edit(cb: CallbackQuery):
        log.info(
            "CB news_edit: from=%s data=%s",
            cb.from_user.id if cb.from_user else "?", cb.data,
        )
        await cb.answer()
        if not await _is_owner_cb(cb):
            log.warning("CB news_edit: not owner")
            return
        draft_id = cb.data.split(":", 1)[1]
        store = _store()
        draft = store.get(draft_id)
        if not draft:
            await cb.answer("Черновик не найден", show_alert=True)
            return
        if draft.status in ("published", "rejected"):
            await cb.answer(f"Уже {draft.status}", show_alert=True)
            return

        _state_set_awaiting_news_edit(draft_id)
        await cb.answer("Жду текст правки в следующем сообщении.", show_alert=False)
        try:
            await _send_dm_html(
                cb.bot,
                "✏️ <b>Жду правку</b>\n\n"
                f"draft_id: <code>{html.escape(draft.draft_id, quote=False)}</code>\n\n"
                "Напиши, что исправить в посте. Например: «сделай короче», "
                "«убери сарказм», «добавь объяснение для новичков».\n\n"
                "Чтобы отменить — отправь <code>cancel</code>.",
            )
        except Exception:
            pass

    @dp.message(F.text)
    async def on_owner_text(message):
        # пускаем только владельца и только если бот ждёт правку
        if not OWNER_CHAT_ID:
            return
        if str(message.from_user.id) != str(OWNER_CHAT_ID).lstrip("@"):
            return
        feedback = (message.text or "").strip()
        if not feedback:
            return
        cancel = feedback.lower() in ("cancel", "отмена", "/cancel", "/отмена")

        # Stage 10: author-note edit имеет приоритет над news-edit, если оба
        # state-флага оказались установлены одновременно (на практике — взаимоисключаемы).
        author_id = _state_get_awaiting_author_edit()
        if author_id:
            await _handle_author_edit_feedback(message.bot, author_id, feedback, cancel=cancel)
            return

        draft_id = _state_get_awaiting_news_edit()
        if not draft_id:
            return
        if cancel:
            _state_set_awaiting_news_edit(None)
            try:
                await _send_dm_html(message.bot, "Правка отменена.")
            except Exception:
                pass
            return

        store = _store()
        draft = store.get(draft_id)
        if not draft:
            _state_set_awaiting_news_edit(None)
            try:
                await _send_dm_html(message.bot, "❌ Черновик не найден, правка отменена.")
            except Exception:
                pass
            return
        if draft.status in ("published", "rejected"):
            _state_set_awaiting_news_edit(None)
            try:
                await _send_dm_html(message.bot, f"⚠️ Этот draft уже {draft.status}, правка отменена.")
            except Exception:
                pass
            return

        # Stage 12e — image-intent роутер. Различаем AI vs source-image.
        # Source-намерение пробуем первым: если владелец сказал «обнови превью
        # источника» — это НЕ требует AI-генерации.
        if _looks_like_source_image_request(feedback):
            _state_set_awaiting_news_edit(None)
            await _handle_news_source_image_text_request(message.bot, draft)
            return
        if _looks_like_ai_image_request(feedback):
            _state_set_awaiting_news_edit(None)
            await _handle_news_ai_image_text_request(message.bot, draft)
            return

        if not CLAUDE_API_KEY:
            _state_set_awaiting_news_edit(None)
            try:
                await _send_dm_html(message.bot, "❌ CLAUDE_API_KEY не задан, правка невозможна.")
            except Exception:
                pass
            return

        try:
            await message.bot.send_message(OWNER_CHAT_ID, "✏️ Применяю правку через Claude…")
        except Exception:
            pass

        try:
            ncfg = NewsConfig.from_env()
            claude = Anthropic(api_key=CLAUDE_API_KEY)
            payload = await asyncio.to_thread(
                revise_payload, draft, feedback, ncfg, claude, CLAUDE_MODEL,
            )
        except Exception as e:
            log.exception("news edit Claude crashed: %s", e)
            try:
                await _send_dm_html(message.bot, f"❌ Правка упала: {html.escape(str(e), quote=False)}")
            except Exception:
                pass
            return

        if not payload.get("should_publish"):
            try:
                await _send_dm_html(
                    message.bot,
                    "⚠️ Claude вернул should_publish=false при правке: "
                    + html.escape(str(payload.get("reason", "no reason")), quote=False),
                )
            except Exception:
                pass
            return

        from news.publisher import build_html as _build_html
        from news import NewsItem
        sn = draft.source_news
        item_for_render = NewsItem(
            title=sn.get("title") or "",
            url=sn.get("url") or "",
            source=sn.get("source") or "",
            published_at=sn.get("published_at") or "",
            summary=sn.get("summary") or "",
            assets=list(sn.get("assets") or []),
            category=sn.get("category") or "other",
            sector=sn.get("sector") or "other",
            impact_score=float(sn.get("impact_score") or 0.0),
        )
        # Stage 12f — compact если у draft уже стоит картинка (revise/regenerate
        # сохраняют image), иначе full-format.
        new_html = _build_html(payload, item_for_render, compact=bool(getattr(draft, "image_path", "")))
        draft.post_html = new_html
        draft.claude_json = payload
        draft.revision_count += 1
        draft.status = "revised"
        draft.owner_feedback.append(feedback)
        store.update(draft)
        _state_set_awaiting_news_edit(None)

        try:
            await _send_preview(message.bot, draft)
        except Exception as e:
            log.exception("news edit: send preview failed: %s", e)


# ---------- scheduler-jobs Stage 8a ----------

async def _safe_expire_confirmations_job() -> None:
    try:
        from trading import TradingConfig
        cfg = TradingConfig.from_env()
        bot = _new_trading_bot()
        try:
            from trading import expire_confirmations
            await expire_confirmations(
                config=cfg,
                confirm_path=CONFIRM_TRADES_FILE,
                live_path=LIVE_TRADES_FILE,
                journal_path=LIVE_TRADE_JOURNAL_FILE,
                send_dm=lambda t: _owner_dm(bot, t),
            )
        finally:
            await bot.session.close()
    except Exception as e:
        log.exception("expire_confirmations job crashed: %s", e)


async def _safe_live_reconcile_job() -> None:
    try:
        from trading import TradingConfig
        cfg = TradingConfig.from_env()
        # reconcile только если есть RW-ключи — иначе ничего не сделать
        if not cfg.gate_api_key_rw or not cfg.gate_api_secret_rw:
            return
        bot = _new_trading_bot()
        try:
            from trading import live_reconcile
            await live_reconcile(
                config=cfg,
                confirm_path=CONFIRM_TRADES_FILE,
                live_path=LIVE_TRADES_FILE,
                journal_path=LIVE_TRADE_JOURNAL_FILE,
                send_dm=lambda t: _owner_dm(bot, t),
            )
        finally:
            await bot.session.close()
    except Exception as e:
        log.exception("live_reconcile job crashed: %s", e)


async def _safe_auto_trade_tick_job() -> None:
    """Scheduler job: каждые AUTO_TRADE_TICK_INTERVAL_MINUTES.

    Тикает активные. Если что-то закрылось — DM владельцу + (опционально) канал.
    """
    try:
        from trading import TradingConfig, TradeContext, tick_open_trades
        cfg = TradingConfig.from_env()
        if not cfg.auto_trade_enabled:
            return
        if cfg.trading_mode != "paper":
            return

        bot = _new_trading_bot()
        try:
            claude = Anthropic(api_key=CLAUDE_API_KEY) if cfg_use_claude_for_trades() else None
            ctx = TradeContext(
                config=cfg,
                trades_path=PAPER_TRADES_FILE,
                journal_path=TRADE_JOURNAL_FILE,
                owner_chat_id=OWNER_CHAT_ID,
                channel_id=CHANNEL_ID,
                send_fn=_make_trade_send_fn(bot),
                state=_make_trade_state_helpers(),
                claude=claude,
                claude_model=CLAUDE_MODEL,
                market_snapshot_provider=_make_trade_market_snapshot,
            )
            res = await tick_open_trades(ctx)
            closed = res.get("closed", []) or []
            log.info("auto_trade_tick: closed=%d", len(closed))
        finally:
            await bot.session.close()
    except Exception as e:
        log.exception("auto_trade_tick_job crashed: %s", e)


# =============================================================================
# NEWS CLI
# =============================================================================

# =============================================================================
# Stage 12d — универсальная отправка post + optional image
#
# Цель: где бы у нас ни был post с (опционально) картинкой — фото идёт ВМЕСТЕ
# с текстом как send_photo(caption=...). Если caption слишком длинный — фото
# с короткой подписью (title + brief + «Полный разбор ниже 👇») и сразу следом
# полный текст. Inline-кнопки (review keyboard) кладутся на ту message, где
# лежит ОСНОВНОЙ текст: если влезло в caption — на photo; если split — на
# второе текстовое сообщение.
# =============================================================================

TELEGRAM_PHOTO_CAPTION_LIMIT = 1024
TELEGRAM_MESSAGE_LIMIT = 4096
PHOTO_CAPTION_SAFE_LIMIT = 1000    # Stage 12g: ближе к hard-лимиту 1024 chars,
                                   # 24 chars запаса для HTML-entity expansion


def _strip_html_tags(s: str) -> str:
    """Грубое снятие HTML-тегов для подсчёта/обрезки plain-длины."""
    import re as _re
    return _re.sub(r"<[^>]+>", "", s or "")


def _build_short_caption(
    post_html: str,
    *,
    title: Optional[str] = None,
    brief: Optional[str] = None,
    limit: int = PHOTO_CAPTION_SAFE_LIMIT,
) -> str:
    """Stage 12d short caption.

    Приоритет:
    1. Если есть title и brief — собираем фиксированный шаблон
       «<b>{title}</b>\n\n<b>Коротко:</b>\n{brief}\n\nПолный разбор ниже 👇».
       Поля экранируются на случай, если пришли как plain text.
    2. Иначе — берём первые целые блоки `\\n\\n` из post_html (чтобы не резать
       HTML посередине тега) пока длина ≤ limit, плюс хвост «Полный разбор ниже 👇».
    3. Если и это не работает (один длинный блок) — берём первые limit символов
       уже снятого html и обрезаем по последнему пробелу.
    """
    tail = "\n\nПолный разбор ниже 👇"

    if title and brief:
        t = title if "<b>" in title else f"<b>{html.escape(title, quote=False)}</b>"
        b = brief if "<" in brief else html.escape(brief, quote=False)
        body = f"{t}\n\n<b>Коротко:</b>\n{b}{tail}"
        if len(body) <= limit:
            return body

    head = (post_html or "").strip()
    chunks = head.split("\n\n")
    out: list[str] = []
    total = 0
    budget = limit - len(tail)
    for ch in chunks:
        if total + len(ch) + 2 > budget:
            break
        out.append(ch)
        total += len(ch) + 2
        if len(out) >= 3:
            break
    if out:
        return "\n\n".join(out).rstrip() + tail

    # последний фолбэк — plain-snippet безопасной длины
    plain = _strip_html_tags(head)[:budget].rstrip()
    if plain.endswith((".", "!", "?")):
        return plain + tail
    last_space = plain.rfind(" ")
    if last_space > 0:
        plain = plain[:last_space]
    return plain + "…" + tail


async def send_post_with_optional_image(
    bot: Bot,
    chat_id: str,
    post_html: str,
    image_path: Optional[str] = None,
    *,
    parse_mode: str = ParseMode.HTML,
    disable_web_page_preview: bool = True,
    title: Optional[str] = None,
    brief: Optional[str] = None,
    reply_markup=None,
) -> None:
    """Универсальная отправка post + optional image (Stage 12d).

    Использует одно из трёх:
    - send_message — если image_path пустой / файла нет.
    - send_photo с full caption — если image_path есть и `len(post_html) ≤
      PHOTO_CAPTION_SAFE_LIMIT`. Кнопки (reply_markup) идут на photo.
    - send_photo с short caption + send_message с полным text — если caption
      не помещается. Кнопки идут на ВТОРОЕ (текстовое) сообщение, чтобы они
      были рядом с полным разбором.
    """
    if not chat_id:
        log.warning("send_post: chat_id пустой, skip")
        return

    img: Optional[Path] = None
    if image_path:
        try:
            cand = Path(image_path)
            if cand.exists():
                img = cand
            else:
                log.warning("post image_path не существует: %s — шлю без фото", image_path)
        except Exception as e:
            log.warning("post image_path bad: %s (%s)", image_path, e)

    if img is None:
        chunks = split_html_for_telegram(post_html, limit=TELEGRAM_MESSAGE_LIMIT)
        if not chunks:
            return
        last_idx = len(chunks) - 1
        for i, chunk in enumerate(chunks):
            await bot.send_message(
                chat_id, chunk,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_web_page_preview,
                reply_markup=reply_markup if i == last_idx else None,
            )
        return

    photo = FSInputFile(str(img))

    # Stage 14: всегда photo+caption одним сообщением, без split.
    # Upstream (truncate cascade + final_caption_guard в news pipeline,
    # caption-fit в market posts) гарантирует ≤ 1024 chars.
    # Если caption > 1024 — это баг upstream, падаем с TelegramBadRequest.
    await bot.send_photo(
        chat_id, photo,
        caption=post_html,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
    )


# --- адаптеры под существующие сигнатуры (NewsPublisher.SendFn / PreviewSendFn) ---

async def _news_send(
    bot: Bot,
    chat_id: str,
    text: str,
    image_path: Optional[str] = None,
) -> None:
    """Адаптер под NewsPublisher.SendFn — делегирует в universal helper."""
    await send_post_with_optional_image(bot, chat_id, text, image_path, reply_markup=None)


async def _news_preview_send(
    bot: Bot,
    text: str,
    kb_dict: dict,
    image_path: Optional[str] = None,
    meta: Optional[dict] = None,
) -> None:
    """Stage 14 — превью владельцу: header + (опц.guard) + сам пост с кнопками.

    Полученный пост шлётся точно как в канал (photo+caption или text-only).
    Header и guard идут отдельными короткими сообщениями ДО поста, чтобы
    визуально не загрязнять сам пост.
    """
    if not OWNER_CHAT_ID:
        log.warning("news preview: OWNER_CHAT_ID не задан, skip")
        return

    if meta:
        draft_id = str(meta.get("draft_id") or "")[:8]
        sector = str(meta.get("sector") or "-")
        impact = int(meta.get("impact") or 0)
        tone = str(meta.get("tone") or "-")
        header_text = (
            f"🧪 Превью #{html.escape(draft_id)} · "
            f"sector={html.escape(sector)} · impact={impact} · tone={html.escape(tone)}"
        )
        try:
            await bot.send_message(
                OWNER_CHAT_ID, header_text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception as e:
            log.warning("news preview header send failed: %s", e)

        guard_reasons = list(meta.get("guard_reasons") or [])
        if guard_reasons:
            guard_text = "🚫 <b>Publish-guard заблокировал автопубликацию:</b>\n" + "\n".join(
                f"• {html.escape(r, quote=False)}" for r in guard_reasons[:6]
            )
            try:
                await bot.send_message(
                    OWNER_CHAT_ID, guard_text,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except Exception as e:
                log.warning("news preview guard send failed: %s", e)

    await send_post_with_optional_image(
        bot, OWNER_CHAT_ID, text, image_path,
        reply_markup=_keyboard_from_dict(kb_dict) if kb_dict else None,
    )


def _market_snapshot_for_news() -> dict:
    """Снимаем BTC (+ best-effort ETH) для контекста Claude — без причинно-следственной связи."""
    snapshot: dict = {}
    try:
        m = Market(spot_symbol="BTC/USDT", swap_symbol="BTC/USDT:USDT")
        t = m.ticker()
        if t:
            snapshot["BTC"] = {
                "price": t.get("price"),
                "change_24h": t.get("change_24h"),
                "high_24h": t.get("high_24h"),
                "low_24h": t.get("low_24h"),
            }
        f = m.funding()
        if f is not None:
            snapshot["BTC_funding"] = f
        oi = m.open_interest()
        if oi is not None:
            snapshot["BTC_open_interest"] = oi
    except Exception as e:
        log.warning("market snapshot для news не доступен: %s", e)

    try:
        eth = Market(spot_symbol="ETH/USDT", swap_symbol="ETH/USDT:USDT")
        t = eth.ticker()
        if t:
            snapshot["ETH"] = {
                "price": t.get("price"),
                "change_24h": t.get("change_24h"),
            }
    except Exception:
        pass
    return snapshot


def _news_image_path_for_hash(news_hash_str: str) -> Path:
    """Stable cache path по news_hash. Stage 12b P2.8."""
    return NEWS_IMAGES_DIR / f"{news_hash_str}.png"


def _generate_news_image_sync(item, payload: dict) -> Optional[str]:
    """Stage 12b: синхронная генерация (без OpenAI deps в news/) — кэш по news_hash.

    Возвращает path к файлу или None. Никогда не кидает исключение.
    """
    if not OPENAI_API_KEY:
        log.info("news image: OPENAI_API_KEY пуст, пропускаем")
        return None

    from news import news_hash, image_prompt_for

    h = news_hash(item)
    out_path = _news_image_path_for_hash(h)
    if out_path.exists():
        log.info("news image cache hit: %s", out_path.name)
        return str(out_path)

    prompt = image_prompt_for(item, payload.get("image_prompt_hint") or "")
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
    except Exception as e:
        log.warning("news image: OpenAI init failed: %s", e)
        return None

    generated = generate_image(client, prompt, out_path)
    if generated:
        log.info("news image generated: %s (prompt %d chars)", out_path.name, len(prompt))
        return str(generated)
    return None


async def _news_image_provider(item, payload: dict) -> Optional[str]:
    """async-обёртка для orchestrator (image_provider контракт)."""
    return await asyncio.to_thread(_generate_news_image_sync, item, payload)


async def run_news_now_cmd() -> None:
    from news import NewsConfig, run_news_now
    news_cfg = NewsConfig.from_env()
    if not CLAUDE_API_KEY:
        raise RuntimeError("CLAUDE_API_KEY не задан — без Claude news_now работать не может")
    claude = Anthropic(api_key=CLAUDE_API_KEY)
    bot = _new_trading_bot()
    try:
        result = await run_news_now(
            config=news_cfg,
            cache_path=NEWS_CACHE_FILE,
            history_path=NEWS_HISTORY_FILE,
            owner_chat_id=OWNER_CHAT_ID,
            channel_id=CHANNEL_ID,
            send_fn=lambda chat_id, text, image_path=None: _news_send(bot, chat_id, text, image_path),
            claude=claude,
            claude_model=CLAUDE_MODEL,
            market_snapshot=_market_snapshot_for_news(),
            drafts_path=NEWS_DRAFTS_FILE,
            preview_send_fn=lambda text, kb, image_path=None, meta=None: _news_preview_send(bot, text, kb, image_path, meta),
            image_provider=_news_image_provider,
            counter_get=_state_get_news_post_counter,
            counter_inc=_state_inc_news_post_counter,
        )
        log.info("news_now result: %s", result)
        # Stage 10+: учёт в контент-миксе
        try:
            decision = (result or {}).get("decision")
            sector = (result or {}).get("sector") or "news"
            title = (result or {}).get("chosen_title") or ""
            if decision == "preview_sent":
                _log_post_event(sector, published_to="owner",
                                title=title, source="news_scan")
            elif decision == "published_channel":
                _log_post_event(sector, published_to="channel",
                                title=title, source="news_scan")
            elif decision == "sent_owner":
                _log_post_event(sector, published_to="owner",
                                title=title, source="news_scan")
        except Exception:
            pass
    finally:
        await bot.session.close()


async def run_news_scan_cmd() -> None:
    from news import NewsConfig, run_news_scan
    news_cfg = NewsConfig.from_env()
    await run_news_scan(config=news_cfg, cache_path=NEWS_CACHE_FILE)


# =============================================================================
# Stage 12c — persistence-check
# =============================================================================

def _check_json_file(path: Path, expected_kind: str) -> tuple[bool, str, int]:
    """Возвращает (ok, summary, size_bytes). expected_kind: 'list' | 'dict'."""
    if not path.exists():
        return (True, "missing (нормально, создастся при первом save)", 0)
    try:
        size = path.stat().st_size
    except OSError as e:
        return (False, f"stat failed: {e}", 0)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return (False, f"INVALID JSON: {e}", size)
    if expected_kind == "list":
        if not isinstance(data, list):
            return (False, f"expected list, got {type(data).__name__}", size)
        return (True, f"list, items={len(data)}", size)
    if expected_kind == "dict":
        if not isinstance(data, dict):
            return (False, f"expected dict, got {type(data).__name__}", size)
        return (True, f"dict, keys={len(data)}", size)
    return (True, "ok", size)


def _scheduler_alive_hint() -> tuple[bool, str]:
    """Эвристика: scheduler.log mtime в пределах 10 мин → бот, скорее всего, работает.

    Не точная проверка (нет PID-файла), но достаточна как индикатор.
    """
    log_path = OUTPUTS / "scheduler.log"
    if not log_path.exists():
        return (False, "scheduler.log нет → бот ни разу не запускался в этой папке")
    try:
        mtime = datetime.fromtimestamp(log_path.stat().st_mtime, tz=timezone.utc)
    except OSError as e:
        return (False, f"stat failed: {e}")
    age_s = (datetime.now(tz=timezone.utc) - mtime).total_seconds()
    if age_s <= 600:
        return (True, f"scheduler.log mtime {int(age_s)}s назад — бот живой")
    minutes = int(age_s // 60)
    return (False, f"scheduler.log mtime {minutes} мин назад — бот, скорее всего, остановлен")


def run_persistence_check_cmd() -> None:
    """Stage 12c — сводка по всем JSON-store. Без Claude/OpenAI/биржи. Read-only."""

    print("=" * 78)
    print("PERSISTENCE CHECK — deposit_ai")
    print(f"timestamp: {datetime.now(tz=timezone.utc).isoformat(timespec='seconds')}")
    print("=" * 78)
    overall_ok = True

    # --- 1. state.json -------------------------------------------------------
    print("\n[1] state.json")
    s_ok, s_summary, s_size = _check_json_file(STATE_FILE, "dict")
    overall_ok = overall_ok and s_ok
    print(f"  file: {STATE_FILE.name} | size: {s_size} B | {s_summary}")
    state = load_state()
    print(f"  state loaded OK: post_count={state.get('post_count', 0)}, "
          f"last_image_at={state.get('last_image_at', 0)}, "
          f"last_partner_at={state.get('last_partner_at', 0)}")
    print(f"  awaiting_news_edit_for:   {state.get('awaiting_news_edit_for') or '—'}")
    print(f"  awaiting_author_edit_for: {state.get('awaiting_author_edit_for') or '—'}")
    print(f"  content_mix_log:          {len(state.get('content_mix_log') or [])} events")
    print(f"  trade_message_index:      {len(state.get('trade_message_index') or {})} entries")
    print(f"  gate_screenshots cache:   {len(state.get('gate_screenshots') or {})} entries")
    print(f"  author_notes_week:        key={state.get('author_notes_week_key', '—')} "
          f"count={state.get('author_notes_week_count', 0)}")

    # --- 2. news_drafts.json -------------------------------------------------
    print("\n[2] news_drafts.json")
    n_ok, n_summary, n_size = _check_json_file(NEWS_DRAFTS_FILE, "list")
    overall_ok = overall_ok and n_ok
    print(f"  file: {NEWS_DRAFTS_FILE.name} | size: {n_size} B | {n_summary}")
    try:
        from news import DraftStore as _NDS
        store = _NDS(NEWS_DRAFTS_FILE)
        all_drafts = store.list_all()
        pending = store.list_pending()
        by_status: dict[str, int] = {}
        with_image = 0
        with_guard = 0
        for d in all_drafts:
            by_status[d.status] = by_status.get(d.status, 0) + 1
            if getattr(d, "image_path", ""):
                with_image += 1
            if getattr(d, "guard_reasons", []):
                with_guard += 1
        print(f"  total: {len(all_drafts)} | pending_review+revised: {len(pending)}")
        print(f"  by status: {dict(sorted(by_status.items())) or '—'}")
        print(f"  drafts с image_path:    {with_image}")
        print(f"  drafts с guard_reasons: {with_guard}")
        if pending:
            for d in pending[:5]:
                title = (d.source_news.get("title") or "")[:60]
                print(f"    pending {d.draft_id} | rev={d.revision_count} | "
                      f"image={'yes' if d.image_path else 'no'} | {title}")
    except Exception as e:
        print(f"  [ERR] DraftStore load crashed: {e}")
        overall_ok = False

    # --- 3. confirm_trades.json ---------------------------------------------
    print("\n[3] confirm_trades.json")
    c_ok, c_summary, c_size = _check_json_file(CONFIRM_TRADES_FILE, "list")
    overall_ok = overall_ok and c_ok
    print(f"  file: {CONFIRM_TRADES_FILE.name} | size: {c_size} B | {c_summary}")
    try:
        from trading import ConfirmTradesStore as _CTS
        store = _CTS(CONFIRM_TRADES_FILE)
        all_ct = store.load()
        by_status: dict[str, int] = {}
        for t in all_ct:
            by_status[t.status] = by_status.get(t.status, 0) + 1
        print(f"  total: {len(all_ct)} | awaiting: {len(store.pending())} | "
              f"active_or_pending_live: {len(store.active_or_pending_live())}")
        print(f"  by status: {dict(sorted(by_status.items())) or '—'}")
    except Exception as e:
        print(f"  [ERR] ConfirmTradesStore load crashed: {e}")
        overall_ok = False

    # --- 4. live_trades.json -------------------------------------------------
    print("\n[4] live_trades.json")
    l_ok, l_summary, l_size = _check_json_file(LIVE_TRADES_FILE, "list")
    overall_ok = overall_ok and l_ok
    print(f"  file: {LIVE_TRADES_FILE.name} | size: {l_size} B | {l_summary}")
    try:
        from trading import LiveTradesStore as _LTS
        store = _LTS(LIVE_TRADES_FILE)
        all_lt = store.load()
        by_status: dict[str, int] = {}
        with_orders = 0
        for t in all_lt:
            by_status[t.status] = by_status.get(t.status, 0) + 1
            if t.entry_order_id or t.sl_order_id or t.tp_order_id:
                with_orders += 1
        print(f"  total: {len(all_lt)} | active_or_pending_live: {len(store.active_or_pending_live())}")
        print(f"  by status: {dict(sorted(by_status.items())) or '—'}")
        print(f"  с exchange order_ids:    {with_orders}")
    except Exception as e:
        print(f"  [ERR] LiveTradesStore load crashed: {e}")
        overall_ok = False

    # --- 5. paper_trades.json ------------------------------------------------
    print("\n[5] paper_trades.json")
    p_ok, p_summary, p_size = _check_json_file(PAPER_TRADES_FILE, "list")
    overall_ok = overall_ok and p_ok
    print(f"  file: {PAPER_TRADES_FILE.name} | size: {p_size} B | {p_summary}")
    try:
        from trading import PaperBroker as _PB, TradingConfig as _TC
        cfg = _TC.from_env()
        broker = _PB(cfg, PAPER_TRADES_FILE)
        all_pt = broker.load_open_trades()
        active = broker.active_trades()
        by_status: dict[str, int] = {}
        for t in all_pt:
            by_status[t.status] = by_status.get(t.status, 0) + 1
        print(f"  total: {len(all_pt)} | active (pending+open): {len(active)}")
        print(f"  by status: {dict(sorted(by_status.items())) or '—'}")
    except Exception as e:
        print(f"  [ERR] PaperBroker load crashed: {e}")
        overall_ok = False

    # --- 6. trade_journal.json + live_trade_journal.json --------------------
    print("\n[6] trade journals")
    tj_ok, tj_summary, tj_size = _check_json_file(TRADE_JOURNAL_FILE, "list")
    overall_ok = overall_ok and tj_ok
    print(f"  paper journal:    {TRADE_JOURNAL_FILE.name} | size: {tj_size} B | {tj_summary}")
    lj_ok, lj_summary, lj_size = _check_json_file(LIVE_TRADE_JOURNAL_FILE, "list")
    overall_ok = overall_ok and lj_ok
    print(f"  live  journal:    {LIVE_TRADE_JOURNAL_FILE.name} | size: {lj_size} B | {lj_summary}")

    # --- 7. вспомогательные ------------------------------------------------
    print("\n[7] supporting stores")
    extras = [
        (NEWS_HISTORY_FILE,  "list", "news_history (dedup window 48h)"),
        (NEWS_CACHE_FILE,    "list", "news_cache (last batch)"),
        (AUTHOR_NOTES_FILE,  "list", "author_notes_drafts"),
        (HISTORY_FILE,       "list", "history (legacy posts)"),
    ]
    for path, kind, label in extras:
        ok, summary, size = _check_json_file(path, kind)
        overall_ok = overall_ok and ok
        print(f"  {label:32s} {path.name:30s} | {size:>7} B | {summary}")

    # --- 8. scheduler liveness hint -----------------------------------------
    print("\n[8] scheduler status (heuristic)")
    alive, hint = _scheduler_alive_hint()
    print(f"  {'[ALIVE]' if alive else '[STOPPED?]'} {hint}")

    # --- 9. итог -------------------------------------------------------------
    print("\n" + "=" * 78)
    if overall_ok:
        print("[OK] persistence check passed — все JSON-файлы валидны")
    else:
        print("[WARN] есть проблемы в одном или более store — смотри выше")
    print("=" * 78)


async def run_news_source_image_test_cmd(url: str) -> None:
    """Stage 12e — самотест source-image extractor.

    GET <url>, парсим og:image / twitter:image / article:image / link rel="image_src",
    скачиваем найденную картинку в outputs/news_source_images, отправляем владельцу.
    Не вызывает OpenAI.
    """
    if not url or not url.lower().startswith(("http://", "https://")):
        print("❌ нужен http(s) URL аргументом: --news-source-image-test https://...")
        return
    if not OWNER_CHAT_ID:
        print("⚠️ OWNER_CHAT_ID не задан — картинка скачается, но не уйдёт в TG.")

    from news import NewsItem, NewsSourceImageExtractor, news_hash, NewsConfig
    item = NewsItem(
        title="source-image smoke test",
        url=url,
        source=url.split("/")[2] if "//" in url else "",
        published_at=datetime.utcnow().isoformat(timespec="seconds"),
        summary="",
        assets=[],
        category="other",
        sector="other",
        impact_score=0.0,
    )
    cfg = NewsConfig.from_env()
    extractor = NewsSourceImageExtractor(Path(cfg.news_source_image_save_dir))

    print(f"source-image-test: url = {url}")
    print(f"source-image-test: news_hash = {news_hash(item)}")
    print(f"source-image-test: save_dir = {cfg.news_source_image_save_dir}")

    local_path, src_url = await asyncio.to_thread(extractor.get_source_image, item)
    if not local_path:
        print("[FAIL] og:image / twitter:image / article:image не найдено или не скачалось")
        return
    print(f"[OK] source image saved: {local_path}")
    print(f"[OK] source url: {src_url}")

    if not OWNER_CHAT_ID:
        return
    bot = _new_trading_bot()
    try:
        caption = (
            "🧪 <b>Stage 12e — source image smoke test</b>\n\n"
            f"page: <code>{html.escape(url, quote=False)[:120]}</code>\n"
            f"img:  <code>{html.escape(src_url or '', quote=False)[:120]}</code>\n"
            f"file: <code>{html.escape(Path(local_path).name, quote=False)}</code>"
        )
        await bot.send_photo(
            OWNER_CHAT_ID, FSInputFile(local_path),
            caption=caption,
            parse_mode=ParseMode.HTML,
        )
    finally:
        await bot.session.close()


async def run_news_image_test_cmd() -> None:
    """Stage 12b — самотест image-generation pipeline.

    Создаёт синтетический NewsItem (sector=ai_crypto, impact=85), прогоняет через
    _news_image_provider (включая sector-prompt + OpenAI gpt-image), отсылает
    результат владельцу. Не публикует ничего в канал. Не трогает state.
    """
    if not OPENAI_API_KEY:
        print("❌ OPENAI_API_KEY не задан — image-test невозможен.")
        return
    if not OWNER_CHAT_ID:
        print("⚠️ OWNER_CHAT_ID не задан — картинка сгенерируется но не уйдёт в TG.")

    from news import NewsItem, news_hash, image_prompt_for, SECTOR_IMAGE_HINTS
    item = NewsItem(
        title="Stage 12b image smoke test — abstract AI-crypto",
        url=f"smoke://stage-12b/{datetime.utcnow().isoformat(timespec='seconds')}",
        source="bot.py --news-image-test",
        published_at=datetime.utcnow().isoformat(timespec="seconds"),
        summary="synthetic test for image generation pipeline; not a real news item",
        assets=["BTC"],
        category="other",
        sector="ai_crypto",
        impact_score=85.0,
    )
    fake_payload = {"image_prompt_hint": ""}   # пусть упадёт на sector template
    h = news_hash(item)
    print(f"image-test: news_hash = {h}")
    print(f"image-test: cache path = {_news_image_path_for_hash(h)}")
    print(f"image-test: prompt = {image_prompt_for(item, '')[:120]}…")
    print(f"image-test: sector_template_chars = {len(SECTOR_IMAGE_HINTS.get('ai_crypto',''))}")

    img_path = await _news_image_provider(item, fake_payload)
    if not img_path:
        print("[FAIL] генерация не удалась (см. лог выше)")
        return
    print(f"[OK] image сгенерирован: {img_path}")

    if not OWNER_CHAT_ID:
        return
    bot = _new_trading_bot()
    try:
        caption = (
            "🧪 <b>Stage 12b — image smoke test</b>\n\n"
            f"sector: <code>ai_crypto</code> | impact: <code>85</code>\n"
            f"news_hash: <code>{html.escape(h, quote=False)}</code>\n"
            f"file: <code>{html.escape(Path(img_path).name, quote=False)}</code>"
        )
        await bot.send_photo(
            OWNER_CHAT_ID, FSInputFile(img_path),
            caption=caption,
            parse_mode=ParseMode.HTML,
        )
    finally:
        await bot.session.close()


async def run_news_debug_cmd() -> None:
    from news import NewsConfig, run_news_debug
    news_cfg = NewsConfig.from_env()
    await run_news_debug(
        config=news_cfg,
        cache_path=NEWS_CACHE_FILE,
        history_path=NEWS_HISTORY_FILE,
    )


# =============================================================================
# AUTHOR NOTES CLI (Stage 10)
# =============================================================================

def _state_get_author_notes_week_count() -> int:
    """Сколько author_notes опубликовано в текущей ISO-неделе (по UTC)."""
    s = load_state()
    today = datetime.now(tz=timezone.utc).isocalendar()
    key = f"{today.year}-{today.week:02d}"
    if s.get("author_notes_week_key") != key:
        return 0
    try:
        return int(s.get("author_notes_week_count") or 0)
    except (TypeError, ValueError):
        return 0


def _state_increment_author_notes_week_count() -> None:
    s = load_state()
    today = datetime.now(tz=timezone.utc).isocalendar()
    key = f"{today.year}-{today.week:02d}"
    if s.get("author_notes_week_key") != key:
        s["author_notes_week_count"] = 1
        s["author_notes_week_key"] = key
    else:
        s["author_notes_week_count"] = int(s.get("author_notes_week_count") or 0) + 1
    s["last_author_note_at"] = datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
    save_state(s)


async def _author_note_preview_send(bot: Bot, text: str, kb_dict: dict) -> None:
    if not OWNER_CHAT_ID:
        log.warning("author_note preview: OWNER_CHAT_ID не задан, skip")
        return
    await bot.send_message(
        OWNER_CHAT_ID, text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=_keyboard_from_dict(kb_dict),
    )


async def _author_note_send(bot: Bot, chat_id: str, text: str) -> None:
    if not chat_id:
        log.warning("author_note send: chat_id пустой, skip")
        return
    await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def run_author_note_now_cmd(rubric_key: str | None = None) -> None:
    """Stage 10: сгенерировать одну author_note и отправить владельцу на ревью."""
    from author_notes import AuthorNoteConfig, run_author_note_now
    cfg = AuthorNoteConfig.from_env()
    if not cfg.enable_author_notes:
        print("ENABLE_AUTHOR_NOTES=false — пропускаем")
        return
    if not CLAUDE_API_KEY:
        raise RuntimeError("CLAUDE_API_KEY не задан — author_note невозможен")
    claude = Anthropic(api_key=CLAUDE_API_KEY)
    bot = _new_trading_bot()
    try:
        result = await run_author_note_now(
            config=cfg,
            claude=claude,
            claude_model=CLAUDE_MODEL,
            drafts_path=AUTHOR_NOTES_FILE,
            owner_chat_id=OWNER_CHAT_ID,
            channel_id=CHANNEL_ID,
            send_fn=lambda chat_id, text: _author_note_send(bot, chat_id, text),
            preview_send_fn=lambda text, kb: _author_note_preview_send(bot, text, kb),
            rubric_key=rubric_key,
            context=_market_snapshot_for_news(),
        )
        log.info("author_note result: %s", result)
        # Stage 10+: учёт в контент-миксе
        try:
            decision = (result or {}).get("decision")
            rub = (result or {}).get("rubric") or rubric_key or ""
            title_hint = rub or "author_note"
            if decision == "preview_sent":
                _log_post_event("author_note", published_to="owner",
                                title=title_hint, source="author_note_cli")
            elif decision == "dry_run":
                _log_post_event("author_note", published_to="owner",
                                title=title_hint, source="author_note_cli")
            elif decision == "published":
                _log_post_event("author_note", published_to="channel",
                                title=title_hint, source="author_note_cli")
        except Exception:
            pass
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        await bot.session.close()


async def run_author_notes_cmd() -> None:
    """Stage 10: список pending author_note drafts."""
    from author_notes import AuthorNoteStore
    store = AuthorNoteStore(AUTHOR_NOTES_FILE)
    pending = store.list_pending()
    if not pending:
        print("Нет pending author_note drafts.")
        return
    print(f"Pending author_notes ({len(pending)}):\n")
    for d in pending:
        title = (d.claude_json or {}).get("title") or d.rubric
        print(
            f"  draft_id: {d.draft_id} | status: {d.status} | rev: {d.revision_count}\n"
            f"    rubric : {d.rubric}\n"
            f"    title  : {title}\n"
            f"    created: {d.created_at}\n"
        )


async def run_publish_author_note_cmd(draft_id: str) -> None:
    """Stage 10: опубликовать конкретный author_note в канал (если флаги пускают)."""
    from author_notes import AuthorNoteStore, AuthorNoteConfig
    cfg = AuthorNoteConfig.from_env()
    store = AuthorNoteStore(AUTHOR_NOTES_FILE)
    draft = store.get(draft_id)
    if not draft:
        print(f"Draft {draft_id} не найден.")
        return
    if draft.status in ("published", "rejected"):
        print(f"Draft {draft_id} уже {draft.status}.")
        return
    if cfg.author_note_dry_run:
        print("AUTHOR_NOTE_DRY_RUN=true — публикация в канал заблокирована.")
        return
    if not CHANNEL_ID:
        print("CHANNEL_ID не задан в .env.")
        return

    bot = _new_trading_bot()
    try:
        await bot.send_message(CHANNEL_ID, draft.post_html,
                               parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    finally:
        await bot.session.close()
    draft.status = "published"
    store.update(draft)
    _state_increment_author_notes_week_count()
    try:
        _log_post_event(
            "author_note", published_to="channel",
            title=((draft.claude_json or {}).get("title") or draft.rubric or "")[:120],
            source="publish_author_note_cli",
        )
    except Exception:
        pass
    print(f"OK: author_note {draft_id} опубликован в {CHANNEL_ID}.")


async def run_reject_author_note_cmd(draft_id: str) -> None:
    """Stage 10: пометить author_note rejected."""
    from author_notes import AuthorNoteStore
    store = AuthorNoteStore(AUTHOR_NOTES_FILE)
    draft = store.get(draft_id)
    if not draft:
        print(f"Draft {draft_id} не найден.")
        return
    if draft.status in ("published", "rejected"):
        print(f"Draft {draft_id} уже {draft.status}.")
        return
    draft.status = "rejected"
    store.update(draft)
    print(f"OK: author_note {draft_id} помечен rejected.")


async def _safe_author_note_job() -> None:
    """Scheduler job: один раз в день пытается сгенерить author_note,
    если квота недели не выбрана. Превью уходит владельцу на ревью.
    """
    try:
        from author_notes import AuthorNoteConfig
        cfg = AuthorNoteConfig.from_env()
        if not cfg.enable_author_notes:
            return
        used = _state_get_author_notes_week_count()
        if used >= max(0, cfg.author_notes_per_week):
            log.info("author_note job: квота недели уже выбрана (%d/%d), skip",
                     used, cfg.author_notes_per_week)
            return
        await run_author_note_now_cmd(rubric_key=None)
    except Exception as e:
        log.exception("author_note job crashed: %s", e)


# =============================================================================
# Stage 13 — Weekly diary
# =============================================================================

async def _weekly_diary_preview_send(bot: Bot, text: str, kb_dict: dict) -> None:
    if not OWNER_CHAT_ID:
        log.warning("weekly_diary preview: OWNER_CHAT_ID не задан, skip")
        return
    await bot.send_message(
        OWNER_CHAT_ID, text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=_keyboard_from_dict(kb_dict),
    )


async def _weekly_diary_send(bot: Bot, chat_id: str, text: str) -> None:
    if not chat_id:
        log.warning("weekly_diary send: chat_id пустой, skip")
        return
    await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)


async def run_weekly_diary_now_cmd() -> None:
    """Stage 13: собрать дневник недели по history.json и отправить владельцу на ревью."""
    from weekly_diary import WeeklyDiaryConfig, run_weekly_diary_now
    cfg = WeeklyDiaryConfig.from_env()
    if not cfg.enable_weekly_diary:
        print("ENABLE_WEEKLY_DIARY=false — пропускаем")
        return
    if not CLAUDE_API_KEY:
        raise RuntimeError("CLAUDE_API_KEY не задан — weekly_diary невозможен")
    claude = Anthropic(api_key=CLAUDE_API_KEY)
    bot = _new_trading_bot()
    try:
        result = await run_weekly_diary_now(
            config=cfg,
            claude=claude,
            claude_model=CLAUDE_MODEL,
            history_path=HISTORY_FILE,
            drafts_path=WEEKLY_DIARY_FILE,
            owner_chat_id=OWNER_CHAT_ID,
            channel_id=CHANNEL_ID,
            send_fn=lambda chat_id, text: _weekly_diary_send(bot, chat_id, text),
            preview_send_fn=lambda text, kb: _weekly_diary_preview_send(bot, text, kb),
        )
        log.info("weekly_diary result: %s", result)
        try:
            if (result or {}).get("decision") == "preview_sent":
                _log_post_event("weekly_diary", published_to="owner",
                                title="Дневник недели", source="weekly_diary_cli")
        except Exception:
            pass
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        await bot.session.close()


async def _safe_weekly_diary_job() -> None:
    """Scheduler job: воскресенье 19:00 — собрать дневник недели и отправить
    владельцу на ревью."""
    try:
        from weekly_diary import WeeklyDiaryConfig
        cfg = WeeklyDiaryConfig.from_env()
        if not cfg.enable_weekly_diary:
            return
        await run_weekly_diary_now_cmd()
    except Exception as e:
        log.exception("weekly_diary job crashed: %s", e)


async def run_news_drafts_cmd() -> None:
    """Stage 6b: показать pending news drafts."""
    from news import DraftStore
    store = DraftStore(NEWS_DRAFTS_FILE)
    pending = store.list_pending()
    if not pending:
        print("Нет pending черновиков.")
        return
    print(f"Pending news drafts ({len(pending)}):\n")
    for d in pending:
        sn = d.source_news or {}
        print(
            f"  draft_id: {d.draft_id} | status: {d.status} | rev: {d.revision_count}\n"
            f"    sector: {sn.get('sector') or '-'} | impact: {int(sn.get('impact_score') or 0)}\n"
            f"    title : {(sn.get('title') or '')[:120]}\n"
        )


async def run_publish_news_draft_cmd(draft_id: str) -> None:
    """Stage 6b: опубликовать конкретный draft в канал."""
    from news import DraftStore, NewsDeduplicator, NewsItem
    store = DraftStore(NEWS_DRAFTS_FILE)
    draft = store.get(draft_id)
    if not draft:
        print(f"Draft {draft_id} не найден.")
        return
    if draft.status in ("published", "rejected"):
        print(f"Draft {draft_id} уже {draft.status}.")
        return
    reasons = _publish_guard_reasons()
    if reasons:
        print("Публикация заблокирована:")
        for r in reasons:
            print("  - " + r)
        return

    bot = _new_trading_bot()
    try:
        await bot.send_message(
            CHANNEL_ID, draft.post_html,
            parse_mode=ParseMode.HTML, disable_web_page_preview=False,
        )
    finally:
        await bot.session.close()

    draft.status = "published"
    store.update(draft)
    try:
        dedup = NewsDeduplicator(NEWS_HISTORY_FILE)
        sn = draft.source_news
        item = NewsItem(
            title=sn.get("title") or "",
            url=sn.get("url") or "",
            source=sn.get("source") or "",
            published_at=sn.get("published_at") or "",
            summary=sn.get("summary") or "",
            assets=list(sn.get("assets") or []),
            category=sn.get("category") or "other",
            sector=sn.get("sector") or "other",
            impact_score=float(sn.get("impact_score") or 0.0),
        )
        short = (draft.claude_json.get("short_summary") or "").strip() if isinstance(draft.claude_json, dict) else ""
        dedup.remember(item, "published_channel", short_summary=short)
    except Exception as e:
        log.warning("publish_news_draft: history.remember failed: %s", e)
    try:
        sn = draft.source_news or {}
        _log_post_event(
            sn.get("sector") or "news",
            published_to="channel",
            title=(sn.get("title") or "")[:120],
            source="publish_news_draft_cli",
        )
    except Exception:
        pass
    print(f"OK: draft {draft_id} опубликован в {CHANNEL_ID}.")


async def run_content_mix_cmd() -> None:
    """Stage 10+: показать 7-дневный content-mix breakdown + recommendation."""
    res = compute_content_mix()
    pct = lambda c: int(round(res["shares"].get(c, 0.0) * 100))
    tgt = lambda c: int(round(res["target"].get(c, 0.0) * 100))
    lines: list[str] = []
    lines.append(f"=== Content mix (last {CONTENT_MIX_WINDOW_DAYS} days) ===")
    lines.append(f"mode used:   {res['mode']}  (channel-only if >= {CONTENT_MIX_CHANNEL_MODE_MIN} channel events)")
    lines.append(f"total_posts: {res['total_posts']}  (other: {res['other_count']})")
    lines.append("")
    lines.append(f"{'category':<14} {'count':>5}  {'now':>5}  {'target':>7}")
    for cat in CONTENT_MIX_TARGET:
        lines.append(f"{cat:<14} {res['counts'][cat]:>5}  {pct(cat):>4}%  {tgt(cat):>6}%")
    lines.append("")
    lines.append("overrepresented:  " + (", ".join(res["overrepresented"]) or "-"))
    lines.append("underrepresented: " + (", ".join(res["underrepresented"]) or "-"))
    lines.append("")
    lines.append(f"recommended next type: {res['recommended']}")
    lines.append(f"reason: {res['reason']}")
    print("\n".join(lines))


async def run_reject_news_draft_cmd(draft_id: str) -> None:
    """Stage 6b: пометить конкретный draft rejected."""
    from news import DraftStore, NewsDeduplicator, NewsItem
    store = DraftStore(NEWS_DRAFTS_FILE)
    draft = store.get(draft_id)
    if not draft:
        print(f"Draft {draft_id} не найден.")
        return
    if draft.status in ("published", "rejected"):
        print(f"Draft {draft_id} уже {draft.status}.")
        return
    draft.status = "rejected"
    store.update(draft)
    try:
        dedup = NewsDeduplicator(NEWS_HISTORY_FILE)
        sn = draft.source_news
        item = NewsItem(
            title=sn.get("title") or "",
            url=sn.get("url") or "",
            source=sn.get("source") or "",
            published_at=sn.get("published_at") or "",
            summary=sn.get("summary") or "",
            assets=list(sn.get("assets") or []),
            category=sn.get("category") or "other",
            sector=sn.get("sector") or "other",
            impact_score=float(sn.get("impact_score") or 0.0),
        )
        dedup.remember(item, "rejected_by_owner", short_summary="rejected by owner")
    except Exception as e:
        log.warning("reject_news_draft: history.remember failed: %s", e)
    print(f"OK: draft {draft_id} помечен rejected.")


async def _safe_news_scan_job() -> None:
    """Scheduler job: собираем новости и DM владельцу если есть сильная новость.

    Работает в рамках NEWS_DRY_RUN=true / NEWS_PUBLISH_TO_CHANNEL=false по умолчанию —
    публикация в канал не случится без явных флагов.
    """
    try:
        await run_news_now_cmd()
    except Exception as e:
        log.exception("news scan crashed: %s", e)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--post-now", action="store_true",
                        help="опубликовать один пост и выйти")
    parser.add_argument("--trade-now", action="store_true",
                        help="(legacy) tick активных + scan нового setup")
    parser.add_argument("--trade-scan-now", action="store_true",
                        help="один раз сканировать рынок и открыть paper-сделку при наличии setup")
    parser.add_argument("--trade-tick-now", action="store_true",
                        help="продвинуть активные paper-сделки по последней свече (TP/SL/expired)")
    parser.add_argument("--trade-review-last", action="store_true",
                        help="взять последнюю закрытую сделку и сделать Claude-разбор в DM (без канала)")
    parser.add_argument("--publish-last-trade", action="store_true",
                        help="опубликовать последнюю закрытую сделку в канал (или DRY_RUN-превью владельцу)")
    parser.add_argument("--paper-backtest", action="store_true",
                        help="прогнать rule-based backtest на исторических свечах")
    parser.add_argument("--bars", type=int, default=500,
                        help="количество анализируемых свечей для --paper-backtest (по умолчанию 500)")
    parser.add_argument("--news-now", action="store_true",
                        help="собрать новости и отправить один новостной пост (DM/канал по флагам)")
    parser.add_argument("--news-scan", action="store_true",
                        help="собрать новости, показать топ-5 по impact_score, без Claude и без публикации")
    parser.add_argument("--news-debug", action="store_true",
                        help="детальный отчёт: sector / impact / decision / reason по каждой новости")
    parser.add_argument("--news-image-test", action="store_true",
                        help="(Stage 12b) проверить image-generation pipeline на синтетической новости (ai_crypto)")
    parser.add_argument("--news-source-image-test", type=str, default=None, metavar="URL",
                        help="(Stage 12e) проверить source-image extractor: достать og:image из URL")
    parser.add_argument("--persistence-check", action="store_true",
                        help="(Stage 12c) read-only сводка по всем JSON-store: state, news_drafts, "
                             "confirm/live/paper trades, journals, scheduler heuristic")
    # Stage 6b — review/approval flow
    parser.add_argument("--news-drafts", action="store_true",
                        help="(Stage 6b) показать pending news drafts (в т.ч. revised)")
    parser.add_argument("--publish-news-draft", type=str, default=None,
                        metavar="DRAFT_ID",
                        help="(Stage 6b) опубликовать конкретный draft в канал, если флаги разрешают")
    parser.add_argument("--reject-news-draft", type=str, default=None,
                        metavar="DRAFT_ID",
                        help="(Stage 6b) пометить конкретный draft rejected")
    # Stage 10 — author voice layer
    parser.add_argument("--author-note-now", action="store_true",
                        help="(Stage 10) сгенерировать одну author_note и отправить владельцу на ревью")
    parser.add_argument("--author-note-rubric", type=str, default=None,
                        metavar="RUBRIC_KEY",
                        help="(Stage 10) явная рубрика для --author-note-now: "
                             "what_i_understood / embarrassing_thought / bad_idea_of_day / "
                             "small_victory / missed_move / almost_believed / hamster_dialog")
    parser.add_argument("--author-notes", action="store_true",
                        help="(Stage 10) показать pending author_note drafts")
    parser.add_argument("--publish-author-note", type=str, default=None,
                        metavar="DRAFT_ID",
                        help="(Stage 10) опубликовать конкретный author_note в канал")
    parser.add_argument("--reject-author-note", type=str, default=None,
                        metavar="DRAFT_ID",
                        help="(Stage 10) пометить конкретный author_note rejected")
    parser.add_argument("--content-mix", action="store_true",
                        help="(Stage 10+) показать 7-дневный content-mix breakdown + recommendation")
    # Stage 13 — weekly diary
    parser.add_argument("--weekly-now", action="store_true",
                        help="(Stage 13) собрать дневник недели по history.json и отправить владельцу на ревью")
    # Stage 11 — render trade-card on demand
    parser.add_argument("--render-last-trade-visual", action="store_true",
                        help="(Stage 11) отрендерить trade-card для последней сделки и отправить владельцу")
    parser.add_argument("--render-trade-visual", type=str, default=None,
                        metavar="TRADE_ID",
                        help="(Stage 11) отрендерить trade-card для конкретной сделки по id")
    # Stage 8a — confirm-mode (real Gate.io futures с обязательной кнопкой)
    parser.add_argument("--confirm-trade-now", action="store_true",
                        help="(Stage 8a) найти setup и отправить план с кнопками подтверждения в OWNER_CHAT_ID")
    parser.add_argument("--expire-confirmations-now", action="store_true",
                        help="(Stage 8a) пометить awaiting_confirmation, висящие дольше CONFIRM_TIMEOUT_MINUTES")
    parser.add_argument("--live-reconcile-now", action="store_true",
                        help="(Stage 8a) сверить локальный state с открытыми позициями/ордерами на Gate.io")
    parser.add_argument("--kill-switch-status", action="store_true",
                        help="(Stage 8a) показать статус KILL_SWITCH, активные сделки, дневной PnL")
    args = parser.parse_args()

    if args.post_now:
        asyncio.run(run_once())
    elif args.trade_scan_now:
        asyncio.run(run_trade_scan_now_cmd())
    elif args.trade_tick_now:
        asyncio.run(run_trade_tick_now_cmd())
    elif args.trade_review_last:
        asyncio.run(run_trade_review_last_cmd())
    elif args.publish_last_trade:
        asyncio.run(run_publish_last_trade_cmd())
    elif args.trade_now:
        asyncio.run(run_trade_now_cmd())
    elif args.paper_backtest:
        asyncio.run(run_paper_backtest_cmd(args.bars))
    elif args.news_now:
        asyncio.run(run_news_now_cmd())
    elif args.news_scan:
        asyncio.run(run_news_scan_cmd())
    elif args.news_debug:
        asyncio.run(run_news_debug_cmd())
    elif args.news_image_test:
        asyncio.run(run_news_image_test_cmd())
    elif args.news_source_image_test:
        asyncio.run(run_news_source_image_test_cmd(args.news_source_image_test))
    elif args.persistence_check:
        run_persistence_check_cmd()
    elif args.news_drafts:
        asyncio.run(run_news_drafts_cmd())
    elif args.publish_news_draft:
        asyncio.run(run_publish_news_draft_cmd(args.publish_news_draft))
    elif args.reject_news_draft:
        asyncio.run(run_reject_news_draft_cmd(args.reject_news_draft))
    elif args.author_note_now:
        asyncio.run(run_author_note_now_cmd(args.author_note_rubric))
    elif args.author_notes:
        asyncio.run(run_author_notes_cmd())
    elif args.publish_author_note:
        asyncio.run(run_publish_author_note_cmd(args.publish_author_note))
    elif args.reject_author_note:
        asyncio.run(run_reject_author_note_cmd(args.reject_author_note))
    elif args.content_mix:
        asyncio.run(run_content_mix_cmd())
    elif args.weekly_now:
        asyncio.run(run_weekly_diary_now_cmd())
    elif args.render_last_trade_visual:
        asyncio.run(run_render_trade_visual_cmd(None))
    elif args.render_trade_visual:
        asyncio.run(run_render_trade_visual_cmd(args.render_trade_visual))
    elif args.confirm_trade_now:
        asyncio.run(run_confirm_trade_now_cmd())
    elif args.expire_confirmations_now:
        asyncio.run(run_expire_confirmations_now_cmd())
    elif args.live_reconcile_now:
        asyncio.run(run_live_reconcile_now_cmd())
    elif args.kill_switch_status:
        asyncio.run(run_kill_switch_status_cmd())
    else:
        asyncio.run(run_scheduler_forever())


if __name__ == "__main__":
    main()
