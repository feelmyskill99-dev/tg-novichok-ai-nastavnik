"""Оркестратор торговых команд.

Точки входа:
    scan_for_new_setup    — найти setup и открыть paper-сделку, если условия выполнены
    tick_open_trades      — продвинуть активные сделки по последней свече
    run_trade_now         — комбинированный (tick + scan); back-compat для --trade-now
    run_paper_backtest    — backtest на исторических свечах (без Claude)
    run_review_last_trade — Claude-разбор последней закрытой сделки (только в DM)
    publish_last_trade    — отправить пост в канал по последней закрытой (или DRY_RUN preview)

Канал НИКОГДА не трогается, если хотя бы один из флагов не выполнен.
Подробности — в _decide_channel_publishing().
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Optional

from anthropic import Anthropic

from .backtest import WARMUP_BARS, run_backtest
from .balance import fetch_paper_equity
from .broker import PaperBroker, PaperTrade, TradePlan
from .channel_post import format_channel_trade_post, format_owner_dm_review
from .config import TradingConfig
from .formatting import (
    format_backtest_report,
    format_trade_close_dm,
    format_trade_plan_dm,
)
from .journal import TradeJournal
from .market_source import TradingMarket
from .review import TradeReviewGenerator
from .risk import RiskChecker
from .setup_detector import RuleBasedSetupDetector


SendFn = Callable[[str, str], Awaitable[None]]   # (chat_id, html_text)
MarketSnapshotFn = Callable[[], dict]
log = logging.getLogger("trading.orchestrator")


# =============================================================================
# StateHelpers — абстракция над state.json (bot.py знает, как читать/писать)
# =============================================================================

@dataclass
class StateHelpers:
    """Колбэки для state.json. Передаются из bot.py.

    Если StateHelpers пустой (всё None) — лимиты по постам в канал не проверяются
    и счётчик не инкрементируется. Используется в backtest и тестовых сценариях.
    """
    get_channel_posts_today: Optional[Callable[[], int]] = None
    increment_channel_posts_today: Optional[Callable[[], None]] = None
    set_last_scan_at: Optional[Callable[[str], None]] = None
    set_last_tick_at: Optional[Callable[[str], None]] = None

    def posts_today(self) -> int:
        if self.get_channel_posts_today is None:
            return 0
        try:
            return int(self.get_channel_posts_today() or 0)
        except Exception:
            return 0

    def bump_posts_today(self) -> None:
        if self.increment_channel_posts_today is None:
            return
        try:
            self.increment_channel_posts_today()
        except Exception as e:
            log.warning("increment_channel_posts_today failed: %s", e)

    def mark_scan(self, ts: str) -> None:
        if self.set_last_scan_at:
            try:
                self.set_last_scan_at(ts)
            except Exception:
                pass

    def mark_tick(self, ts: str) -> None:
        if self.set_last_tick_at:
            try:
                self.set_last_tick_at(ts)
            except Exception:
                pass


@dataclass
class TradeContext:
    """Группа зависимостей, которые нужны и scan, и tick. Чтобы не таскать 10 параметров."""
    config: TradingConfig
    trades_path: Path
    journal_path: Path
    owner_chat_id: str
    channel_id: str
    send_fn: SendFn
    state: StateHelpers = field(default_factory=StateHelpers)
    claude: Optional[Anthropic] = None
    claude_model: str = ""
    market_snapshot_provider: Optional[MarketSnapshotFn] = None


# =============================================================================
# scan: открыть новую paper-сделку, если есть setup
# =============================================================================

async def scan_for_new_setup(ctx: TradeContext, *, auto: bool = False) -> dict:
    """Открывает новую paper-сделку (если setup найден и риск-чек пройден).
    Существующие открытые сделки НЕ трогает — для этого есть tick_open_trades.

    auto=True — поведение для scheduler-job: не спамим DM при каждом no_trade,
    в OWNER пишем только если действительно открыли сделку.
    """
    market = TradingMarket(ctx.config.default_symbol)
    broker = PaperBroker(ctx.config, ctx.trades_path)
    journal = TradeJournal(ctx.journal_path)
    detector = RuleBasedSetupDetector(ctx.config)
    risk = RiskChecker(ctx.config)

    df = market.fetch_ohlcv(ctx.config.default_timeframe, limit=300)
    if df is None or len(df) < 50:
        msg = "рыночные данные недоступны"
        journal.log_setup_skipped(f"scan: {msg}")
        if not auto:
            await ctx.send_fn(ctx.owner_chat_id,
                              f"<b>⚠️ [PAPER SCAN]</b> {msg}, решение: <i>no_trade</i>.")
        return {"opened": None, "reason": msg}

    now_ts = datetime.now(tz=timezone.utc)
    last_bar_index = len(df) - 1

    active = broker.active_trades()
    if len(active) >= ctx.config.max_open_trades:
        msg = f"уже есть активная сделка ({len(active)})"
        if not auto:
            await ctx.send_fn(ctx.owner_chat_id,
                              f"<b>📒 [PAPER SCAN]</b> {msg}, новая не открывается.")
        return {"opened": None, "reason": msg}

    setup = detector.detect(df)
    if setup.action != "trade":
        reason = setup.reason or "rule-based no_trade"
        journal.log_setup_skipped(reason, setup.rationale_facts)
        if not auto:
            equity, equity_source = fetch_paper_equity(ctx.config)
            await ctx.send_fn(ctx.owner_chat_id,
                              f"<b>📒 [PAPER SCAN]</b> решение: <i>no_trade</i>.\n"
                              f"Причина: {reason}\n"
                              f"Баланс: {equity:.2f} USDT ({equity_source})")
        # auto-режим: НЕ спамим DM при no_trade (только в журнал)
        ctx.state.mark_scan(now_ts.isoformat(timespec="seconds"))
        return {"opened": None, "reason": reason}

    equity, equity_source = fetch_paper_equity(ctx.config)
    risk_res = risk.check(
        direction=setup.direction or "long",
        entry=setup.entry or 0.0,
        stop_loss=setup.stop_loss or 0.0,
        take_profit=setup.take_profit or 0.0,
        leverage=ctx.config.max_leverage,
        equity_usdt=equity,
        open_trades_count=len(active),
    )
    if not risk_res.ok:
        reason = f"risk check: {risk_res.reason}"
        journal.log_setup_skipped(reason, setup.rationale_facts)
        if not auto:
            await ctx.send_fn(ctx.owner_chat_id,
                              f"<b>📒 [PAPER SCAN]</b> решение: <i>no_trade</i>.\n"
                              f"Причина: {reason}\n"
                              f"Баланс: {equity:.2f} USDT ({equity_source})")
        ctx.state.mark_scan(now_ts.isoformat(timespec="seconds"))
        return {"opened": None, "reason": reason}

    # --- открываем paper-сделку ---
    plan = TradePlan(
        symbol=ctx.config.default_symbol,
        direction=setup.direction or "long",
        entry=setup.entry or 0.0,
        stop_loss=setup.stop_loss or 0.0,
        take_profit=setup.take_profit or 0.0,
        leverage=ctx.config.max_leverage,
        position_size=risk_res.position_size,
        risk_amount_usdt=risk_res.risk_amount_usdt,
        rr=risk_res.rr,
        rationale=_plain_rationale(setup.rationale_facts),
        meta={"facts": setup.rationale_facts, "source": "auto" if auto else "manual"},
    )
    new_trade = broker.create_plan(plan, bar_index=last_bar_index, now=now_ts)
    broker.open_trade(new_trade, open_price=new_trade.entry,
                      bar_index=last_bar_index, now=now_ts)

    broker.save_open_trades(active + [new_trade])
    journal.log_plan_created(new_trade)

    # --- разбор + DM/канал ---
    review = _make_reviewer(ctx).review(
        new_trade, event_type="opened",
        market_snapshot=_snapshot(ctx),
        for_channel=_event_can_go_to_channel(ctx.config, "opened"),
    )
    decision, block_reason = await _publish_event(
        ctx, new_trade, review, event_type="opened",
        equity=equity, equity_source=equity_source,
    )
    journal.log_trade_opened(
        new_trade,
        published_to_owner=True,
        published_to_channel=(decision == "published_channel"),
        channel_posted_at=now_ts.isoformat(timespec="seconds") if decision == "published_channel" else None,
        claude_review=review,
    )
    ctx.state.mark_scan(now_ts.isoformat(timespec="seconds"))
    return {"opened": new_trade, "decision": decision, "block_reason": block_reason}


# =============================================================================
# tick: продвинуть активные сделки
# =============================================================================

async def tick_open_trades(ctx: TradeContext) -> dict:
    """Тикает все pending/open сделки на последней свече. Открытие новых — НЕ задача tick."""
    market = TradingMarket(ctx.config.default_symbol)
    broker = PaperBroker(ctx.config, ctx.trades_path)
    journal = TradeJournal(ctx.journal_path)

    df = market.fetch_ohlcv(ctx.config.default_timeframe, limit=300)
    if df is None or len(df) < 5:
        return {"closed": [], "reason": "no market data"}

    now_ts = datetime.now(tz=timezone.utc)
    last_bar_index = len(df) - 1
    last_bar = df.iloc[-1]

    trades = broker.load_open_trades()
    closed_this_run: list[PaperTrade] = []
    still_active: list[PaperTrade] = []
    for trade in trades:
        if trade.status not in ("pending", "open"):
            continue
        broker.tick(
            trade,
            bar_index=last_bar_index,
            open_=float(last_bar["Open"]),
            high=float(last_bar["High"]),
            low=float(last_bar["Low"]),
            close=float(last_bar["Close"]),
            ts=now_ts,
        )
        if trade.status in ("pending", "open"):
            still_active.append(trade)
        else:
            closed_this_run.append(trade)

    broker.save_open_trades(still_active)

    # Каждая закрытая сделка → review → DM/канал → journal
    for trade in closed_this_run:
        review = _make_reviewer(ctx).review(
            trade, event_type="closed",
            market_snapshot=_snapshot(ctx),
            for_channel=_event_can_go_to_channel(ctx.config, "closed"),
        )
        decision, block_reason = await _publish_event(
            ctx, trade, review, event_type="closed",
        )
        journal.log_trade_closed(
            trade,
            published_to_owner=True,
            published_to_channel=(decision == "published_channel"),
            channel_posted_at=now_ts.isoformat(timespec="seconds") if decision == "published_channel" else None,
            claude_review=review,
        )

    ctx.state.mark_tick(now_ts.isoformat(timespec="seconds"))
    return {
        "closed": closed_this_run,
        "still_active": still_active,
    }


# =============================================================================
# run_trade_now — back-compat: tick → scan
# =============================================================================

async def run_trade_now(
    *,
    config: TradingConfig,
    trades_path: Path,
    journal_path: Path,
    owner_chat_id: str,
    channel_id: str,
    send_fn: SendFn,
    state: Optional[StateHelpers] = None,
    claude: Optional[Anthropic] = None,
    claude_model: str = "",
    market_snapshot_provider: Optional[MarketSnapshotFn] = None,
    auto: bool = False,
) -> dict:
    """Существовавшая ранее команда. Сначала тикает, затем пытается открыть новую сделку."""
    if config.trading_mode != "paper":
        raise RuntimeError(f"TRADING_MODE={config.trading_mode}: реализован только paper")
    ctx = TradeContext(
        config=config,
        trades_path=trades_path,
        journal_path=journal_path,
        owner_chat_id=owner_chat_id,
        channel_id=channel_id,
        send_fn=send_fn,
        state=state or StateHelpers(),
        claude=claude,
        claude_model=claude_model,
        market_snapshot_provider=market_snapshot_provider,
    )
    tick_res = await tick_open_trades(ctx)
    scan_res = await scan_for_new_setup(ctx, auto=auto)
    return {"tick": _summarize_tick(tick_res), "scan": _summarize_scan(scan_res)}


# =============================================================================
# review-last-trade и publish-last-trade
# =============================================================================

async def run_review_last_trade(
    *,
    config: TradingConfig,
    trades_path: Path,
    journal_path: Path,
    owner_chat_id: str,
    channel_id: str,
    send_fn: SendFn,
    claude: Optional[Anthropic] = None,
    claude_model: str = "",
    market_snapshot_provider: Optional[MarketSnapshotFn] = None,
) -> dict:
    """Берёт последнюю закрытую сделку из journal, запускает Claude review, шлёт в DM.

    В канал НЕ публикует (даже при включённых флагах). Это команда «дай посмотреть превью разбора».
    """
    journal = TradeJournal(journal_path)
    rec = journal.find_last_closed_trade()
    if rec is None:
        await send_fn(owner_chat_id, "<b>📒 [REVIEW]</b> в журнале нет закрытых сделок.")
        return {"ok": False, "reason": "no closed trade"}

    fake_trade = _trade_from_journal_record(rec)
    ctx = TradeContext(
        config=config,
        trades_path=trades_path,
        journal_path=journal_path,
        owner_chat_id=owner_chat_id,
        channel_id=channel_id,
        send_fn=send_fn,
        state=StateHelpers(),
        claude=claude,
        claude_model=claude_model,
        market_snapshot_provider=market_snapshot_provider,
    )
    review = _make_reviewer(ctx).review(
        fake_trade, event_type="closed",
        market_snapshot=_snapshot(ctx),
        for_channel=False,
    )
    text = format_owner_dm_review(
        fake_trade, review, event_type="closed",
        publish_decision="sent_owner",
    )
    await send_fn(owner_chat_id, text)
    return {"ok": True, "review_source": review.get("_source"), "trade_id": fake_trade.id}


async def publish_last_trade(
    *,
    config: TradingConfig,
    trades_path: Path,
    journal_path: Path,
    owner_chat_id: str,
    channel_id: str,
    send_fn: SendFn,
    state: Optional[StateHelpers] = None,
    claude: Optional[Anthropic] = None,
    claude_model: str = "",
    market_snapshot_provider: Optional[MarketSnapshotFn] = None,
    dry_run: bool = False,
) -> dict:
    """Команда `--publish-last-trade`. Берёт последнюю закрытую сделку и публикует в канал
    (если флаги разрешают). При dry_run=True — шлёт превью в OWNER с пометкой.

    Эта команда обходит TRADE_PUBLISH_MODE и Claude.should_publish_to_channel,
    потому что это явный «manual publish» — владелец сам решил, что хочет в канал.
    Но дневной лимит и базовые требования (PUBLISH_TRADE_UPDATES_TO_CHANNEL,
    непустой channel_id) всё равно проверяются.
    """
    journal = TradeJournal(journal_path)
    rec = journal.find_last_closed_trade()
    if rec is None:
        await send_fn(owner_chat_id, "<b>📒 [PUBLISH]</b> в журнале нет закрытых сделок.")
        return {"ok": False, "reason": "no closed trade"}

    trade = _trade_from_journal_record(rec)
    state = state or StateHelpers()

    ctx = TradeContext(
        config=config, trades_path=trades_path, journal_path=journal_path,
        owner_chat_id=owner_chat_id, channel_id=channel_id, send_fn=send_fn,
        state=state, claude=claude, claude_model=claude_model,
        market_snapshot_provider=market_snapshot_provider,
    )
    review = _make_reviewer(ctx).review(
        trade, event_type="closed",
        market_snapshot=_snapshot(ctx),
        for_channel=True,
    )

    # DRY_RUN preview — отправляем владельцу с маркером, не трогаем канал
    if dry_run or not config.publish_trade_updates_to_channel or not channel_id:
        preview = format_channel_trade_post(
            trade, review, event_type="closed",
            dry_run_preview=True,
        )
        await send_fn(owner_chat_id, preview)
        why_not = (
            "DRY_RUN forced" if dry_run
            else ("PUBLISH_TRADE_UPDATES_TO_CHANNEL=false" if not config.publish_trade_updates_to_channel
                  else "channel_id пустой")
        )
        return {"ok": True, "decision": "dry_run_preview", "reason": why_not}

    # лимит дня
    if state.posts_today() >= config.trade_max_channel_posts_per_day:
        await send_fn(owner_chat_id,
                      f"<b>📒 [PUBLISH]</b> дневной лимит TRADE_MAX_CHANNEL_POSTS_PER_DAY "
                      f"({config.trade_max_channel_posts_per_day}) исчерпан.")
        return {"ok": False, "decision": "daily_limit"}

    # публикация
    text = format_channel_trade_post(trade, review, event_type="closed")
    await send_fn(channel_id, text)
    state.bump_posts_today()
    await send_fn(owner_chat_id,
                  format_owner_dm_review(trade, review, event_type="closed",
                                         publish_decision="published_channel"))
    return {"ok": True, "decision": "published_channel"}


# =============================================================================
# backtest (без Claude)
# =============================================================================

async def run_paper_backtest(
    *,
    config: TradingConfig,
    bars: int,
    trades_path: Path,
    journal_path: Path,
    send_dm: Optional[Callable[[str], Awaitable[None]]],
) -> dict:
    """Прогон backtest на исторических свечах. Не использует Claude и канал."""
    market = TradingMarket(config.default_symbol)
    detector = RuleBasedSetupDetector(config)
    risk = RiskChecker(config)

    need = max(bars + WARMUP_BARS, WARMUP_BARS + 50)
    df = market.fetch_ohlcv(config.default_timeframe, limit=need)
    if df is None or len(df) < WARMUP_BARS + 5:
        msg = f"недостаточно исторических данных для backtest (need≥{WARMUP_BARS+5}, got {0 if df is None else len(df)})"
        log.warning(msg)
        if send_dm:
            await send_dm(f"<b>⚠️ [PAPER BACKTEST]</b> {msg}")
        return {"ok": False, "reason": msg}

    work_df = df.tail(bars + WARMUP_BARS).copy() if len(df) > bars + WARMUP_BARS else df

    bt_trades_path = trades_path.with_name("paper_trades_backtest.json")
    broker = PaperBroker(config, bt_trades_path)

    result = run_backtest(
        work_df,
        config=config,
        detector=detector,
        risk_checker=risk,
        broker=broker,
        initial_equity=config.paper_equity_usdt,
    )
    broker.save_open_trades(result.closed_trades)

    summary = result.to_summary_dict()
    journal = TradeJournal(journal_path)
    journal.log_backtest({"bars": len(work_df), **summary})

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if send_dm:
        await send_dm(format_backtest_report(result, bars=len(work_df), symbol=config.default_symbol))

    return {"ok": True, **summary}


# =============================================================================
# ВНУТРЕННЕЕ
# =============================================================================

def _make_reviewer(ctx: TradeContext) -> TradeReviewGenerator:
    return TradeReviewGenerator(
        claude=ctx.claude,
        model=ctx.claude_model,
        config=ctx.config,
    )


def _snapshot(ctx: TradeContext) -> dict:
    if ctx.market_snapshot_provider is None:
        return {}
    try:
        return ctx.market_snapshot_provider() or {}
    except Exception as e:
        log.warning("market_snapshot_provider failed: %s", e)
        return {}


def _event_can_go_to_channel(cfg: TradingConfig, event_type: str) -> bool:
    """Дешёвая предварительная проверка — стоит ли вообще просить Claude думать про канал.
    Полная проверка — в _decide_channel_publishing."""
    if not cfg.publish_trade_updates_to_channel:
        return False
    mode = cfg.trade_publish_mode
    if mode in ("owner_only", "manual_only"):
        return False
    if mode == "opened_only" and event_type != "opened":
        return False
    if mode == "closed_only" and event_type != "closed":
        return False
    return True


def _decide_channel_publishing(
    cfg: TradingConfig,
    review: dict,
    *,
    trade: PaperTrade,
    event_type: str,
    state: StateHelpers,
) -> tuple[bool, str]:
    """Возвращает (channel_allowed, block_reason).

    Все условия из ТЗ Stage 7 §8 + censorship из §9 проверяются здесь.
    """
    mode = cfg.trade_publish_mode
    if mode == "owner_only":
        return False, "TRADE_PUBLISH_MODE=owner_only"
    if mode == "manual_only":
        return False, "TRADE_PUBLISH_MODE=manual_only (только --publish-last-trade)"
    if mode == "opened_only" and event_type != "opened":
        return False, "TRADE_PUBLISH_MODE=opened_only"
    if mode == "closed_only" and event_type != "closed":
        return False, "TRADE_PUBLISH_MODE=closed_only"

    if not cfg.publish_trade_updates_to_channel:
        return False, "PUBLISH_TRADE_UPDATES_TO_CHANNEL=false"

    if event_type == "closed":
        reason = (trade.close_reason or "").lower()
        if reason == "tp" and not cfg.trade_publish_wins:
            return False, "TRADE_PUBLISH_WINS=false"
        if reason == "sl" and not cfg.trade_publish_losses:
            return False, "TRADE_PUBLISH_LOSSES=false"
        if reason == "expired" and not cfg.trade_publish_expired:
            return False, "TRADE_PUBLISH_EXPIRED=false"

    if not review.get("should_publish_to_channel"):
        return False, "Claude: should_publish_to_channel=false"

    impact = float(review.get("channel_impact_score") or 0)
    if impact < cfg.trade_min_channel_impact:
        return False, f"channel_impact_score {impact:.0f} < {cfg.trade_min_channel_impact}"

    if state.posts_today() >= cfg.trade_max_channel_posts_per_day:
        return False, f"дневной лимит TRADE_MAX_CHANNEL_POSTS_PER_DAY ({cfg.trade_max_channel_posts_per_day})"

    return True, ""


async def _publish_event(
    ctx: TradeContext,
    trade: PaperTrade,
    review: dict,
    *,
    event_type: str,
    equity: float | None = None,
    equity_source: str | None = None,
) -> tuple[str, str]:
    """Шлёт DM владельцу и (опционально) пост в канал. Возвращает (decision, block_reason).

    decision ∈ {'published_channel', 'sent_owner', 'channel_blocked', 'dry_run_preview'}.
    """
    channel_allowed, block_reason = _decide_channel_publishing(
        ctx.config, review,
        trade=trade, event_type=event_type, state=ctx.state,
    )

    # ---- DM владельцу: одно сообщение на событие ----
    # opened → компактный «PAPER TRADE OPENED» c Claude beginner_mistake
    # closed → полный owner-review (включает «📊 План был такой» + PnL + Claude narrative)
    if channel_allowed and ctx.channel_id:
        text = format_channel_trade_post(trade, review, event_type=event_type)
        await ctx.send_fn(ctx.channel_id, text)
        ctx.state.bump_posts_today()
        owner_msg = format_owner_dm_review(
            trade, review, event_type=event_type,
            publish_decision="published_channel",
        )
        await ctx.send_fn(ctx.owner_chat_id, owner_msg)
        return "published_channel", ""

    # канал заблокирован/выключен — отправляем владельцу один разбор
    if event_type == "opened" and equity is not None:
        owner_msg = format_trade_plan_dm(
            trade,
            equity_usdt=equity,
            paper_equity_source=equity_source or "env",
            beginner_mistake=review.get("beginner_mistake") or None,
        )
        # дополним пометкой «канал не трогали» одной строкой
        owner_msg += f"\n\n<i>[Owner DM] paper-trade event. В канал НЕ отправлено: {block_reason}</i>"
    else:
        owner_msg = format_owner_dm_review(
            trade, review, event_type=event_type,
            publish_decision="channel_blocked",
            publish_reason=block_reason,
        )
    await ctx.send_fn(ctx.owner_chat_id, owner_msg)
    return "channel_blocked", block_reason


def _plain_rationale(facts: dict | None) -> str:
    if not facts:
        return "rule-based setup"
    parts = []
    if facts.get("trend"):
        parts.append(f"тренд: {facts['trend']}")
    if facts.get("rsi") is not None:
        parts.append(f"RSI {facts['rsi']}")
    if facts.get("distance_to_support_pct") is not None:
        parts.append(f"до support {facts['distance_to_support_pct']}%")
    if facts.get("rr") is not None:
        parts.append(f"RR {facts['rr']}")
    return "; ".join(parts) if parts else "rule-based setup"


def _trade_from_journal_record(rec: dict) -> PaperTrade:
    """Восстанавливает PaperTrade из записи trade_closed для review/publish-команд.

    Запись содержит полный план (entry/stop/take/leverage/rr/risk_amount) — см. journal.log_trade_closed.
    Для совсем старых записей без этих полей подставляются нули, и отображение будет неполным.
    """
    return PaperTrade(
        id=rec.get("trade_id", ""),
        symbol=rec.get("symbol", ""),
        direction=rec.get("direction", "long"),
        entry=float(rec.get("entry") or 0.0),
        stop_loss=float(rec.get("stop_loss") or 0.0),
        take_profit=float(rec.get("take_profit") or 0.0),
        leverage=float(rec.get("leverage") or 0.0),
        position_size=0.0,                                 # не хранится явно
        risk_amount_usdt=float(rec.get("risk_amount_usdt") or 0.0),
        rr=float(rec.get("rr") or 0.0),
        status=rec.get("status", "closed_sl"),
        created_at="",
        created_at_bar=0,
        opened_at=rec.get("opened_at"),
        closed_at=rec.get("closed_at"),
        closed_at_bar=rec.get("closed_at_bar"),
        close_reason=rec.get("close_reason"),
        close_price=rec.get("close_price"),
        pnl_usdt=rec.get("pnl_usdt"),
        r_multiple=rec.get("r_multiple"),
        rationale=rec.get("rationale", "") or "",
    )


def _summarize_tick(res: dict) -> dict:
    closed = res.get("closed", []) or []
    return {
        "closed_count": len(closed),
        "closed_reasons": [t.close_reason for t in closed],
    }


def _summarize_scan(res: dict) -> dict:
    out = {"opened": False, "reason": res.get("reason")}
    if res.get("opened") is not None:
        out["opened"] = True
        out["decision"] = res.get("decision")
        out["block_reason"] = res.get("block_reason")
    return out
