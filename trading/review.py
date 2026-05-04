"""TradeReviewGenerator — Claude генерирует «человеческий» разбор сделки.

Никогда не падает. Если Claude недоступен или вернул мусор — возвращается fallback,
у которого should_publish_to_channel=false, чтобы автомат точно не публиковал
сырой текст в канал.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from anthropic import Anthropic

from .broker import PaperTrade
from .config import TradingConfig


log = logging.getLogger("trading.review")


BRAND = "Депозит под надзором ИИ"


SYSTEM_PROMPT = f"""
Ты — AI-наставник по трейдингу для Telegram-канала «{BRAND}».
Стиль канала: новичок наблюдает за сделкой, строгий AI-наставник объясняет.

Тебе показывают paper-сделку (учебная, виртуальная — реальные ордера НЕ выставляются).
event_type = "opened" или "closed".
Твоя задача — дать живой обучающий разбор, чтобы новичок мог чему-то научиться,
а не воспринимал это как сигнал.

ЗАПРЕЩЕНО:
- слова «сигнал», «точный вход», «повторяйте», «заработали», «ракета», «инсайд»
- «заходим», «лонгуй», «шорти», «покупай», «продавай»
- утверждать, что эта сделка — «пример успешной торговли»
- утверждать прямую связь «новость → движение»
- markdown-обёртка ```json``` или комментарии вне JSON

РАЗРЕШЕНО:
- «учебная paper-сделка», «виртуальная сделка», «торговый план»
- называть ошибку, которую новичок мог бы совершить
- объяснять урок дисциплины, риск-менеджмента, ожидания
- лёгкий юмор без токсичности и без шуток над убытками реальных людей

Если событие не несёт обучающей ценности или сделка слишком слабая —
верни should_publish_to_channel=false. Канал не должен превращаться в ленту входов.

Поле channel_impact_score 0..100 — насколько сильный это разбор для канала:
   90+ — сильный урок (риск-менеджмент сработал, или яркая ошибка)
   70..89 — нормальный разбор
   <70 — слабовато для канала, лучше только в OWNER

Верни СТРОГО валидный JSON без markdown-обёртки:
{{
  "should_publish_to_channel": true|false,
  "channel_impact_score": 0,
  "human_part": "...",
  "mentor_part": "...",
  "beginner_mistake": "...",
  "lesson": "...",
  "conclusion": "...",
  "humor_line": "... или null",
  "hashtags": ["#честный_путь", "#риск_менеджмент"],
  "short_summary": "одна строка для памяти, 8–14 слов"
}}
""".strip()


# =============================================================================
# Public API
# =============================================================================

def build_review_payload(
    trade: PaperTrade,
    *,
    event_type: str,
    market_snapshot: Optional[dict] = None,
    for_channel: bool = True,
) -> dict:
    """Готовит JSON-контекст для Claude. Возвращается dict, не str."""
    return {
        "event_type": event_type,
        "trade": _serialize_trade(trade),
        "market_snapshot": market_snapshot or {},
        "result": _serialize_result(trade, event_type),
        "channel_style": "новичок + строгий AI-наставник",
        "for_channel": for_channel,
    }


class TradeReviewGenerator:
    def __init__(self, claude: Optional[Anthropic], model: str, config: TradingConfig):
        self.claude = claude
        self.model = model
        self.cfg = config

    def review(
        self,
        trade: PaperTrade,
        *,
        event_type: str,
        market_snapshot: Optional[dict] = None,
        for_channel: bool = True,
    ) -> dict:
        """Возвращает dict вида:
            {
              "should_publish_to_channel": bool,
              "channel_impact_score": 0..100,
              "human_part": "...",
              "mentor_part": "...",
              "beginner_mistake": "...",
              "lesson": "...",
              "conclusion": "...",
              "humor_line": "...",
              "hashtags": [...],
              "short_summary": "...",
              "_source": "claude" | "fallback"
            }

        Никогда не кидает исключение. При ошибке — fallback с should_publish=false.
        """
        if not self.cfg.trade_claude_review or self.claude is None:
            return _fallback_review(trade, event_type, "Claude review disabled")

        payload = build_review_payload(
            trade, event_type=event_type,
            market_snapshot=market_snapshot, for_channel=for_channel,
        )

        try:
            try:
                from style_guides import compose_style_context
                style_suffix = compose_style_context("base", "trade")
            except Exception:
                style_suffix = ""
            resp = self.claude.messages.create(
                model=self.model,
                max_tokens=1200,
                system=SYSTEM_PROMPT + (style_suffix or ""),
                messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
            )
            raw = (resp.content[0].text or "").strip()
            if raw.startswith("```"):
                raw = raw.strip("`").strip()
                if raw.lower().startswith("json"):
                    raw = raw[4:].strip()
            data = json.loads(raw)
        except Exception as e:
            log.warning("trade Claude review failed (%s) — fallback", e)
            return _fallback_review(trade, event_type, f"claude error: {e}")

        # дефолты + sanitization
        data.setdefault("should_publish_to_channel", False)
        data.setdefault("channel_impact_score", 0)
        data.setdefault("human_part", "")
        data.setdefault("mentor_part", "")
        data.setdefault("beginner_mistake", "")
        data.setdefault("lesson", "")
        data.setdefault("conclusion", "")
        data.setdefault("humor_line", None)
        data.setdefault("hashtags", [])
        data.setdefault("short_summary", "")
        data["_source"] = "claude"

        # требование «должен быть урок» — если урока нет, в канал не пускаем
        if self.cfg.trade_require_lesson and not str(data.get("lesson", "")).strip():
            data["should_publish_to_channel"] = False

        # фильтр сигнальной лексики
        if self.cfg.trade_no_signal_language and _contains_signal_language(data):
            data["should_publish_to_channel"] = False

        return data


# =============================================================================
# helpers
# =============================================================================

_SIGNAL_PHRASES = (
    "сигнал", "точный вход", "повторяйте", "заработали", "ракета",
    "инсайд", "заходим", "лонгуй", "шорти", "покупай", "продавай",
)


def _contains_signal_language(data: dict) -> bool:
    blob = " ".join(
        str(data.get(k, "") or "")
        for k in ("human_part", "mentor_part", "beginner_mistake", "lesson", "conclusion", "humor_line")
    ).lower()
    return any(phrase in blob for phrase in _SIGNAL_PHRASES)


def _serialize_trade(trade: PaperTrade) -> dict:
    return {
        "id": trade.id,
        "symbol": trade.symbol,
        "direction": trade.direction,
        "entry": trade.entry,
        "stop_loss": trade.stop_loss,
        "take_profit": trade.take_profit,
        "leverage": trade.leverage,
        "rr": trade.rr,
        "risk_amount_usdt": trade.risk_amount_usdt,
        "rationale": trade.rationale,
        "status": trade.status,
        "created_at": trade.created_at,
        "opened_at": trade.opened_at,
        "closed_at": trade.closed_at,
    }


def _serialize_result(trade: PaperTrade, event_type: str) -> dict:
    return {
        "event_type": event_type,
        "status": trade.status,
        "exit_reason": trade.close_reason,
        "close_price": trade.close_price,
        "pnl_usdt": trade.pnl_usdt,
        "r_multiple": trade.r_multiple,
    }


def _fallback_review(trade: PaperTrade, event_type: str, reason: str) -> dict:
    """Безопасный шаблон, когда Claude недоступен. Никогда не разрешает канал."""
    direction = trade.direction or "long"
    if event_type == "opened":
        human = (
            "Открылась учебная paper-сделка. Внутри сразу появляется желание «удвоить ставку», "
            "но это и есть момент, где новичок чаще всего себе мешает."
        )
        mentor = (
            "План понятный: вход у структуры, стоп под уровнем, цель в сторону тренда. "
            "Ничего из этого не значит, что движение точно состоится."
        )
        mistake = (
            "Подвинуть стоп «ещё чуть-чуть», чтобы рынок «не выбил по шуму»."
        )
        lesson = "Правила лучше неудобной фиксации убытка."
        conclusion = "Это виртуальная сделка, реальные ордера не выставлены."
    else:
        reason_str = (trade.close_reason or "expired").lower()
        if reason_str == "tp":
            human = "Цена дошла до цели. Хочется сразу искать следующую сделку и удвоить плечо."
            mentor = (
                "TP — это не повод считать стратегию рабочей по одной попытке. "
                "Серия — да, одна свеча — нет."
            )
            mistake = "Считать одну удачную сделку доказательством, что «теперь точно знаю»."
        elif reason_str == "sl":
            human = "Стоп сработал. Внутри — «надо было чуть подождать»."
            mentor = (
                "Стоп выполнил свою задачу: ограничил убыток. Это не провал, это и есть "
                "риск-менеджмент в работе."
            )
            mistake = "Снять стоп после первого касания и «дать рынку шанс»."
        else:
            human = "Сделка истекла, не дойдя ни до TP, ни до SL."
            mentor = (
                "Иногда правильный исход — это «никаких эмоций»: сетап не сработал в свой "
                "временной горизонт, и план закрылся технически."
            )
            mistake = "Тянуть план «ещё на пару дней» в надежде, что рынок сообразит."
        lesson = "Дисциплина важнее одного исхода."
        conclusion = "Это виртуальная сделка, реальные ордера не выставлены."

    return {
        "should_publish_to_channel": False,
        "channel_impact_score": 0,
        "human_part": human,
        "mentor_part": mentor,
        "beginner_mistake": mistake,
        "lesson": lesson,
        "conclusion": conclusion,
        "humor_line": None,
        "hashtags": ["#честный_путь", "#риск_менеджмент"],
        "short_summary": f"{direction} {trade.symbol}: {trade.close_reason or 'opened'}",
        "_source": "fallback",
        "_fallback_reason": reason,
    }
