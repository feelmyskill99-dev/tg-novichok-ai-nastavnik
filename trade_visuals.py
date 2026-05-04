"""Stage 11 — Trade Visual Renderer.

Строим собственную картинку сделки на базе OHLCV + параметров сделки:
свечной график с горизонтальными линиями Entry / SL / TP / current / Liq
+ summary-блок (symbol, side, leverage, position size, risk %, RR, status).

Не используем реальный screenshot Gate.io как основной источник.
TRADE_VISUAL_MODE=gate_screenshot — опциональный режим, оставлен заглушкой.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import ccxt
import matplotlib

matplotlib.use("Agg")  # без GUI
import matplotlib.pyplot as plt   # noqa: E402
import matplotlib.patheffects as pe  # noqa: E402
import mplfinance as mpf          # noqa: E402
import pandas as pd               # noqa: E402


log = logging.getLogger("trade_visuals")


# =============================================================================
# CONFIG
# =============================================================================

def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _str(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


@dataclass(frozen=True)
class TradeVisualConfig:
    """Stage 11: hybrid visual strategy.

    generated trade-card всегда основной формат (clarity + branding).
    Gate.io screenshot — опциональное 2-е изображение (trust + partner funnel).

    GATE_SCREENSHOT_MODE:
        manual  — использовать только то, что владелец прикрепил
                  через /attach_gate_screenshot (никаких автозапусков playwright)
        browser — если manual нет, пытаться снять public-страницу Gate.io
        off     — вообще не отправлять 2-е изображение
    """
    enable_trade_visuals: bool = True
    trade_visual_mode: str = "hybrid"                  # generated | hybrid
    publish_trade_visuals_to_channel: bool = False
    trade_visual_bars: int = 120
    trade_visual_timeframe: str = "1h"
    enable_gate_screenshots: bool = True
    gate_screenshot_mode: str = "manual"               # manual | browser | off
    attach_gate_screenshot_on_open: bool = True
    attach_gate_screenshot_on_close: bool = True

    @classmethod
    def from_env(cls) -> "TradeVisualConfig":
        return cls(
            enable_trade_visuals=_bool("ENABLE_TRADE_VISUALS", True),
            trade_visual_mode=_str("TRADE_VISUAL_MODE", "hybrid").lower(),
            publish_trade_visuals_to_channel=_bool("PUBLISH_TRADE_VISUALS_TO_CHANNEL", False),
            trade_visual_bars=_int("TRADE_VISUAL_BARS", 120),
            trade_visual_timeframe=_str("TRADE_VISUAL_TIMEFRAME", "1h"),
            enable_gate_screenshots=_bool("ENABLE_GATE_SCREENSHOTS", True),
            gate_screenshot_mode=_str("GATE_SCREENSHOT_MODE", "manual").lower(),
            attach_gate_screenshot_on_open=_bool("ATTACH_GATE_SCREENSHOT_ON_OPEN", True),
            attach_gate_screenshot_on_close=_bool("ATTACH_GATE_SCREENSHOT_ON_CLOSE", True),
        )

    def gate_enabled_for(self, event_type: str) -> bool:
        """Stage 11: GATE_SCREENSHOT_MODE имеет приоритет; manual/browser оба разрешают
        отправку 2-го изображения (manual даже без playwright). off — выключает полностью.
        """
        if self.gate_screenshot_mode == "off":
            return False
        if self.trade_visual_mode == "generated":
            return False
        if not self.enable_gate_screenshots:
            return False
        if event_type == "opened":
            return self.attach_gate_screenshot_on_open
        if event_type == "closed":
            return self.attach_gate_screenshot_on_close
        return False

    @property
    def gate_browser_capture_allowed(self) -> bool:
        """Только в режиме browser имеем право автоматически дёргать Playwright."""
        return (self.gate_screenshot_mode == "browser"
                and self.enable_gate_screenshots
                and self.trade_visual_mode != "generated")


# =============================================================================
# OHLCV
# =============================================================================

def fetch_trade_ohlcv(
    symbol: str,
    timeframe: str = "1h",
    bars: int = 120,
) -> Optional[pd.DataFrame]:
    """Дёргаем OHLCV с Gate.io spot. symbol в формате "BTC/USDT" или "BTC/USDT:USDT" — приводим к spot."""
    spot_symbol = symbol.split(":")[0] if ":" in symbol else symbol
    try:
        ex = ccxt.gateio({"enableRateLimit": True})
        raw = ex.fetch_ohlcv(spot_symbol, timeframe, limit=max(20, bars))
        df = pd.DataFrame(raw, columns=["ts", "Open", "High", "Low", "Close", "Volume"])
        df["ts"] = pd.to_datetime(df["ts"], unit="ms")
        df.set_index("ts", inplace=True)
        return df.tail(bars)
    except Exception as e:
        log.warning("fetch_trade_ohlcv(%s, %s, %d) failed: %s", symbol, timeframe, bars, e)
        return None


# =============================================================================
# PAYLOAD: универсальный dict из PaperTrade / ConfirmTrade / live trade
# =============================================================================

def compose_trade_payload(obj: Any) -> dict:
    """Аккуратно вытащить нужные поля из объекта (PaperTrade, ConfirmTrade, live trade dict)
    в общий формат для рендера. Поддерживает duck-typing.
    """
    def g(name: str, *aliases: str, default=None):
        for n in (name, *aliases):
            if isinstance(obj, dict):
                if n in obj and obj[n] is not None:
                    return obj[n]
            else:
                if hasattr(obj, n):
                    v = getattr(obj, n)
                    if v is not None:
                        return v
        return default

    side = (g("direction", "side") or "long").lower()
    if side in ("buy", "long"):
        side = "long"
    elif side in ("sell", "short"):
        side = "short"

    opened_at = g("opened_at", "open_time", "opened_at_iso", default=None)
    closed_at = g("closed_at", "close_time", default=None)
    duration = _format_duration(opened_at, closed_at)

    return {
        "id":              g("id", "trade_id", default=""),
        "symbol":          g("symbol", default="BTC/USDT"),
        "side":            side,
        "entry":           _float_or_none(g("entry", "entry_price", "open_price")),
        "stop_loss":       _float_or_none(g("stop_loss", "sl", "stop_loss_price")),
        "take_profit":     _float_or_none(g("take_profit", "tp", "take_profit_price")),
        "current_price":   _float_or_none(g("current_price", "last_price", "close_price")),
        "liquidation":     _float_or_none(g("liquidation_price", "liq_price", "liquidation")),
        "leverage":        _float_or_none(g("leverage", default=1.0)),
        "position_size":   _float_or_none(g("position_size", "size", "qty", "amount")),
        "risk_amount":     _float_or_none(g("risk_amount_usdt", "risk_amount", "risk_usdt")),
        "rr":              _float_or_none(g("rr", "risk_reward")),
        "status":          str(g("status", default="open") or "open"),
        "opened_at":       opened_at,
        "closed_at":       closed_at,
        "close_reason":    g("close_reason", "close_cause", default=None),
        "close_price":     _float_or_none(g("close_price", "exit_price")),
        "pnl_usdt":        _float_or_none(g("pnl_usdt", "pnl", "realized_pnl")),
        "r_multiple":      _float_or_none(g("r_multiple", "r")),
        "duration":        duration,
    }


def _format_duration(opened_at, closed_at) -> Optional[str]:
    if not opened_at or not closed_at:
        return None
    try:
        from datetime import datetime as _dt
        o = _dt.fromisoformat(str(opened_at).replace("Z", "+00:00"))
        c = _dt.fromisoformat(str(closed_at).replace("Z", "+00:00"))
        delta = c - o
        secs = int(delta.total_seconds())
        if secs < 60:
            return f"{secs}s"
        if secs < 3600:
            return f"{secs // 60}m"
        h, rem = divmod(secs, 3600)
        return f"{h}h {rem // 60}m"
    except Exception:
        return None


def _float_or_none(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# =============================================================================
# CHART
# =============================================================================

LEVEL_COLORS = {
    "entry":       "#1976d2",   # blue
    "tp":          "#2e7d32",   # green
    "sl":          "#c62828",   # red
    "liq":         "#ef6c00",   # orange
    "current":     "#9e9e9e",   # gray
}


STATUS_LABEL: dict[str, tuple[str, str]] = {
    # raw status → (display, color)
    "pending":               ("PENDING",   "#9e9e9e"),
    "open":                  ("OPEN",      "#1976d2"),
    "active":                ("OPEN",      "#1976d2"),
    "closed_tp":             ("CLOSED TP", "#2e7d32"),
    "closed_take_profit":    ("CLOSED TP", "#2e7d32"),
    "closed_sl":             ("CLOSED SL", "#c62828"),
    "closed_stop_loss":      ("CLOSED SL", "#c62828"),
    "closed_manual":         ("MANUAL",    "#6a1b9a"),
    "closed_error":          ("ERROR",     "#5d4037"),
    "expired":               ("EXPIRED",   "#ef6c00"),
    "cancelled":             ("CANCELLED", "#757575"),
    "awaiting_confirmation": ("AWAITING",  "#0277bd"),
    "approved":              ("APPROVED",  "#1565c0"),
}

BRAND_BOTTOM = "Депозит под надзором ИИ"
BRAND_BOTTOM_SUB = "Не финсовет • Дневник обучения"


def build_trade_chart(
    df: pd.DataFrame,
    payload: dict,
    out_path: Path,
    *,
    title: str = "",
) -> Optional[Path]:
    """Stage 11 trade-card layout:
        [ top bar: SYMBOL · SIDE                          [ STATUS BADGE ] ]
        [ chart with axhlines + chip labels   |  right stats panel        ]
        [ bottom: brand line + дисклеймер                                 ]
    """
    if df is None or len(df) < 5:
        log.warning("build_trade_chart: пустой/короткий df, skip")
        return None

    out_path.parent.mkdir(parents=True, exist_ok=True)

    mc = mpf.make_marketcolors(up="#26a69a", down="#ef5350", edge="inherit",
                               wick="inherit", volume="in")
    style = mpf.make_mpf_style(base_mpf_style="charles", marketcolors=mc, gridstyle=":")

    fig = plt.figure(figsize=(13.5, 7.6), facecolor="white")
    fig.subplots_adjust(left=0.06, right=0.98, top=0.87, bottom=0.18)
    grid = fig.add_gridspec(1, 2, width_ratios=[3.4, 1.0], wspace=0.04)
    ax_chart = fig.add_subplot(grid[0])
    ax_panel = fig.add_subplot(grid[1])

    # --- chart (mplfinance в наш ax) ---
    mpf.plot(
        df, type="candle", style=style,
        ax=ax_chart, axtitle="", volume=False, xrotation=20,
    )
    ax_chart.set_ylabel("Price")
    ax_chart.grid(True, linestyle=":", alpha=0.5)

    # --- horizontal levels + chip labels ---
    levels = [
        ("entry",   payload.get("entry"),         "Entry"),
        ("tp",      payload.get("take_profit"),   "TP"),
        ("sl",      payload.get("stop_loss"),     "SL"),
        ("liq",     payload.get("liquidation"),   "Liq"),
        ("current", payload.get("current_price"), "Current"),
    ]
    drawn_y: list[float] = []
    yaxis_trans = ax_chart.get_yaxis_transform()
    for kind, y, label_text in levels:
        if y is None:
            continue
        try:
            yf = float(y)
        except (TypeError, ValueError):
            continue
        color = LEVEL_COLORS[kind]
        linestyle = "--" if kind in ("entry", "current") else "-"
        ax_chart.axhline(yf, color=color, linewidth=1.4, linestyle=linestyle, alpha=0.85)
        ax_chart.text(
            0.995, yf,
            f"{label_text} {yf:,.2f}",
            transform=yaxis_trans,
            color="white", fontsize=9, fontweight="bold",
            va="center", ha="right",
            bbox=dict(facecolor=color, edgecolor="none", pad=3.0, boxstyle="round,pad=0.25"),
            clip_on=False,
        )
        drawn_y.append(yf)

    # --- markers: open / close ---
    _draw_trade_markers(ax_chart, df, payload)

    # padding по Y чтобы Liq/SL не прилипали
    if drawn_y:
        ymin, ymax = ax_chart.get_ylim()
        spread = max(drawn_y) - min(drawn_y)
        pad = max(spread * 0.05, (ymax - ymin) * 0.02)
        ax_chart.set_ylim(min(ymin, min(drawn_y) - pad), max(ymax, max(drawn_y) + pad))

    # --- top bar: symbol · side + status badge ---
    sym = (payload.get("symbol") or "—").split(":")[0]
    side = (payload.get("side") or "long").upper()
    side_color = "#26a69a" if side == "LONG" else "#ef5350"
    fig.text(
        0.06, 0.945,
        f"{sym}  ·  ",
        fontsize=15, fontweight="bold", color="#212121",
        ha="left", va="center",
    )
    fig.text(
        0.06 + 0.10, 0.945,   # после symbol
        side,
        fontsize=14, fontweight="bold", color=side_color,
        ha="left", va="center",
    )
    status_raw = (payload.get("status") or "open").lower()
    status_label, status_color = STATUS_LABEL.get(status_raw, (status_raw.upper(), "#9e9e9e"))
    fig.text(
        0.98, 0.945,
        f"  {status_label}  ",
        fontsize=11, fontweight="bold", color="white",
        ha="right", va="center",
        bbox=dict(facecolor=status_color, edgecolor="none",
                  pad=4.0, boxstyle="round,pad=0.45"),
    )

    # --- right side stats panel ---
    _draw_stats_panel(ax_panel, payload)

    # --- bottom branding (ниже X-axis labels) ---
    fig.text(
        0.5, 0.040, BRAND_BOTTOM,
        fontsize=10, fontweight="bold",
        ha="center", color="#212121",
    )
    fig.text(
        0.5, 0.014, BRAND_BOTTOM_SUB,
        fontsize=8, color="#9e9e9e", ha="center",
    )

    fig.savefig(out_path, dpi=120, facecolor="white")
    plt.close(fig)
    return out_path


def _draw_trade_markers(ax, df: pd.DataFrame, payload: dict) -> None:
    """Поставить маркеры открытия/закрытия на свечах. Если timestamp вне диапазона df —
    тихо пропускаем (видим только то, что попало в окно)."""
    try:
        from datetime import datetime as _dt

        def _to_idx(iso_ts) -> Optional[int]:
            if not iso_ts:
                return None
            try:
                t = _dt.fromisoformat(str(iso_ts).replace("Z", "+00:00"))
                if t.tzinfo is not None:
                    t = t.replace(tzinfo=None)   # df.index naive
                # ближайший bar: первый, у которого index >= t-1bar
                idx = df.index.get_indexer([pd.Timestamp(t)], method="nearest")[0]
                return int(idx) if idx >= 0 and idx < len(df) else None
            except Exception:
                return None

        # open marker
        opened_idx = _to_idx(payload.get("opened_at"))
        entry = payload.get("entry")
        if opened_idx is not None and entry is not None:
            ax.scatter(
                [opened_idx], [float(entry)],
                marker="o", s=110, color="#1976d2",
                edgecolors="white", linewidths=1.5, zorder=12,
            )

        # close marker
        closed_idx = _to_idx(payload.get("closed_at"))
        close_price = payload.get("close_price") or payload.get("current_price")
        if closed_idx is not None and close_price is not None:
            reason = (payload.get("close_reason") or "").lower()
            color = "#2e7d32" if reason in ("tp", "take_profit") else (
                "#c62828" if reason in ("sl", "stop_loss") else "#6a1b9a"
            )
            ax.scatter(
                [closed_idx], [float(close_price)],
                marker="X", s=140, color=color,
                edgecolors="white", linewidths=1.5, zorder=13,
            )
    except Exception as e:   # pragma: no cover
        log.debug("markers skipped: %s", e)


def _draw_stats_panel(ax, payload: dict) -> None:
    """Right side panel с метриками сделки."""
    ax.axis("off")
    rows: list[tuple[str, str]] = []

    def _fmt(v, *, money: bool = False, signed: bool = False) -> str:
        if v is None:
            return "—"
        try:
            f = float(v)
        except (TypeError, ValueError):
            return str(v)
        if signed:
            sign = "+" if f >= 0 else ""
            return f"{sign}{f:,.2f}" + (" USDT" if money else "")
        return f"{f:,.2f}" + (" USDT" if money else "")

    rows.append(("Entry",    _fmt(payload.get("entry"))))
    rows.append(("SL",       _fmt(payload.get("stop_loss"))))
    rows.append(("TP",       _fmt(payload.get("take_profit"))))
    if payload.get("liquidation") is not None:
        rows.append(("Liq",  _fmt(payload.get("liquidation"))))

    lev = payload.get("leverage")
    rows.append(("Leverage", f"x{lev:g}" if lev is not None else "—"))

    risk_amount = payload.get("risk_amount")
    rows.append(("Risk",     _fmt(risk_amount, money=True) if risk_amount is not None else "—"))

    rr = payload.get("rr")
    rows.append(("RR",       f"{rr:.2f}" if rr is not None else "—"))

    pos = payload.get("position_size")
    rows.append(("Size",     f"{pos:g}" if pos is not None else "—"))

    if payload.get("pnl_usdt") is not None:
        rows.append(("PnL",   _fmt(payload.get("pnl_usdt"), money=True, signed=True)))
    if payload.get("r_multiple") is not None:
        rows.append(("R",     _fmt(payload.get("r_multiple"), signed=True)))
    if payload.get("duration"):
        rows.append(("Duration", str(payload["duration"])))

    # рисуем таблицей: левый столбец label, правый value
    n = len(rows)
    if n == 0:
        return
    y_top = 0.97
    y_step = min(0.085, (y_top - 0.05) / max(n, 1))
    for i, (label, value) in enumerate(rows):
        y = y_top - i * y_step
        ax.text(
            0.05, y, label,
            transform=ax.transAxes,
            fontsize=10, color="#666666",
            ha="left", va="top",
        )
        ax.text(
            0.95, y, value,
            transform=ax.transAxes,
            fontsize=10, fontweight="bold", color="#212121",
            ha="right", va="top",
        )

    # рамка вокруг панели
    ax.add_patch(
        plt.Rectangle(
            (0.0, 0.0), 1.0, 1.0,
            transform=ax.transAxes,
            fill=False, edgecolor="#e0e0e0", linewidth=1.0,
        )
    )


def build_trade_summary_card(payload: dict) -> str:
    """Текстовая шапка под картинку (HTML caption)."""
    sym = payload.get("symbol", "—")
    side = (payload.get("side") or "long").upper()
    side_emoji = "🟢" if side == "LONG" else "🔴"

    leverage = payload.get("leverage")
    pos = payload.get("position_size")
    risk = payload.get("risk_amount")
    rr = payload.get("rr")
    status = (payload.get("status") or "open").lower()

    status_emoji = {
        "pending":               "🕓",
        "open":                  "🟢",
        "active":                "🟢",
        "closed_tp":             "✅",
        "closed_take_profit":    "✅",
        "closed_sl":             "❌",
        "closed_stop_loss":      "❌",
        "closed_manual":         "✋",
        "expired":               "⌛",
        "cancelled":             "🚫",
    }.get(status, "•")

    parts: list[str] = []
    parts.append(f"<b>{side_emoji} {sym}  •  {side}</b>")
    sub = []
    if leverage is not None:
        sub.append(f"x{leverage:g}")
    if pos is not None:
        sub.append(f"size {pos:g}")
    if risk is not None:
        sub.append(f"risk {risk:.2f} USDT")
    if rr is not None:
        sub.append(f"RR {rr:.2f}")
    if sub:
        parts.append(" · ".join(sub))
    parts.append(f"{status_emoji} status: <code>{status}</code>")

    pnl = payload.get("pnl_usdt")
    rmult = payload.get("r_multiple")
    if pnl is not None or rmult is not None:
        bits = []
        if pnl is not None:
            sign = "+" if pnl >= 0 else ""
            bits.append(f"PnL {sign}{pnl:.2f} USDT")
        if rmult is not None:
            sign = "+" if rmult >= 0 else ""
            bits.append(f"R {sign}{rmult:.2f}")
        parts.append(" · ".join(bits))

    return "\n".join(parts)


# =============================================================================
# Высокоуровневая обёртка
# =============================================================================

def save_trade_visual(
    *,
    payload: dict,
    out_dir: Path,
    bars: int = 120,
    timeframe: str = "1h",
    title: Optional[str] = None,
) -> Optional[Path]:
    """Полный цикл: ohlcv → chart → save. Возвращает Path к PNG или None.

    Имя файла: trade_<id_or_symbol>_<event>_<UTC>.png
    """
    symbol = payload.get("symbol") or "BTC/USDT"
    df = fetch_trade_ohlcv(symbol, timeframe=timeframe, bars=bars)
    if df is None:
        return None

    # current_price, если не задан, возьмём из последней свечи
    if payload.get("current_price") is None and not df.empty:
        try:
            payload = {**payload, "current_price": float(df["Close"].iloc[-1])}
        except Exception:
            pass

    out_dir.mkdir(parents=True, exist_ok=True)
    safe_id = (payload.get("id") or symbol.replace("/", "")).replace(":", "")[:24]
    status = (payload.get("status") or "open").lower()
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"trade_{safe_id}_{status}_{ts}.png"

    chart_title = title or _default_title(payload)
    return build_trade_chart(df, payload, out_path, title=chart_title)


def _default_title(payload: dict) -> str:
    sym = payload.get("symbol") or "—"
    side = (payload.get("side") or "long").upper()
    lev = payload.get("leverage")
    rr = payload.get("rr")
    bits = [f"{sym}  ·  {side}"]
    if lev is not None:
        bits.append(f"x{lev:g}")
    if rr is not None:
        bits.append(f"RR {rr:.2f}")
    return "  |  ".join(bits)


# =============================================================================
# Gate.io screenshot (опциональное 2-е изображение)
# =============================================================================

def _gate_pair(symbol: str) -> str:
    """BTC/USDT:USDT → BTC_USDT (формат URL у Gate.io)."""
    sym = (symbol or "BTC/USDT").split(":")[0]
    return sym.replace("/", "_").upper()


def capture_gate_screenshot(
    payload: dict,
    out_dir: Path,
    *,
    timeout_ms: int = 18000,
    viewport_width: int = 1280,
    viewport_height: int = 720,
) -> Optional[Path]:
    """Снять public trading-страницу Gate.io как PNG. Best-effort:

    - если playwright не установлен → None (молча)
    - если страница не открылась за timeout → None
    - не блокирует event-loop: вызывать через asyncio.to_thread()

    Скрин сделан с публичной страницы /trade/<PAIR> — без логина и без приватных данных.
    Это нужно как «нативная подложка партнёрской воронки + контекст реального терминала»,
    а не для подтверждения конкретной сделки.
    """
    try:
        from playwright.sync_api import sync_playwright   # noqa: F401
    except ImportError:
        log.info("playwright не установлен — gate screenshot пропускаем")
        return None
    except Exception as e:
        log.warning("playwright import failed: %s", e)
        return None

    pair = _gate_pair(payload.get("symbol") or "BTC/USDT")
    url = f"https://www.gate.io/trade/{pair}"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_id = (payload.get("id") or pair).replace(":", "")[:24]
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"gate_{safe_id}_{ts}.png"

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                ctx = browser.new_context(
                    viewport={"width": viewport_width, "height": viewport_height},
                    locale="en-US",
                )
                page = ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                # пробуем дождаться основного chart-canvas (TradingView iframe или canvas).
                # Не ставим жёсткое ожидание — fallback на фиксированный sleep.
                try:
                    page.wait_for_selector("canvas, iframe", timeout=6000)
                except Exception:
                    pass
                # дать chart дорисовать свечи + ордера
                try:
                    page.wait_for_timeout(5500)
                except Exception:
                    pass
                # скрыть cookie-banner / region-popup / sign-up-tooltip — чтобы скрин
                # выглядел как реальный терминал, а не как лендинг.
                try:
                    page.evaluate(
                        """() => {
                            const sel = [
                                '.cookie-tip', '.cookie-policy', '.GA-cookie-policy',
                                '[class*=cookie]', '[class*=region-popup]',
                                '[class*=tooltip-tip]',
                                '.banner-region', '.region-tip',
                            ];
                            for (const s of sel) {
                                document.querySelectorAll(s).forEach(el => {
                                    el.style.display = 'none';
                                });
                            }
                        }"""
                    )
                except Exception:
                    pass
                page.screenshot(path=str(out_path), full_page=False)
            finally:
                try:
                    browser.close()
                except Exception:
                    pass
        return out_path if out_path.exists() else None
    except Exception as e:
        log.warning("capture_gate_screenshot failed: %s", e)
        return None


# Обратная совместимость со Stage 11 — старый stub-имя.
def take_gate_screenshot_stub(*, _payload: dict) -> Optional[Path]:   # pragma: no cover
    return None
