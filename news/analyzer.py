"""NewsAnalyzer — отдаём Claude топ-новостей, получаем структурированный JSON поста.

Жёсткие правила в system prompt:
- не выдумывать новости;
- не писать «сигнал», «точно вырастет»;
- отделять факт от предположения;
- разрешённый юмор — лёгкий, без токсичности;
- обязательно указывать источник.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from anthropic import Anthropic

from .config import NewsConfig
from .models import NewsItem

try:
    from style_guides import compose_style_context as _compose_style
except Exception:   # pragma: no cover — модуль может отсутствовать в тестах
    def _compose_style(*_args, **_kwargs) -> str:
        return ""


log = logging.getLogger("news.analyzer")


BRAND = "Депозит под надзором ИИ"


def build_system_prompt(cfg: NewsConfig) -> str:
    humor_rules = _humor_level_rules(cfg.news_humor_level)
    sarcasm_rules = _sarcasm_level_rules(cfg.news_sarcasm_level)
    base = _build_core_prompt(humor_rules, sarcasm_rules)
    style = _compose_style("base", "news")
    return base + (style or "")


def _build_core_prompt(humor_rules: str, sarcasm_rules: str) -> str:
    return f"""
Ты пишешь посты для Telegram-канала «{BRAND}» — живой дневник новичка-трейдера,
которого AI-наставник каждый день ловит за руку, чтобы он не делал глупостей.

Канал — НЕ аналитика, НЕ гуру, НЕ сигналы, НЕ мем-паблик, НЕ новостная помойка.
Канал — мини-сцена: новичок видит новость, хочет среагировать, AI-наставник
спокойно, строго и слегка саркастично объясняет, почему среагировать так — опасно.

ТЫ НЕ ПРИДУМЫВАЕШЬ НОВОСТИ. Тебе дают список реальных новостей (news_batch),
уже отфильтрованных кодом по sector + impact_score. Выбери ОДНУ самую значимую
и сформулируй пост. Не добавляй URL, факты или цифры, которых нет во входе.
Если все слабые — верни should_publish=false.

ЗАПРЕЩЕНО:
- «точно вырастет/упадёт», «заходим», «сигнал», «гарантированный рост»,
  «инсайд», «киты точно покупают», «покупай», «шорти», «лонгуй», «иксы», «туземун»
- давать торговый сигнал или совет покупать/продавать
- утверждать прямую причинно-следственную связь между новостью и ценой
- шутки над жертвами взломов, банкротств, убытков, скамов
- кликбейт «рынок умрёт», «биток улетит»
- начинать пост с штампов: «BTC торгуется на уровне», «Сегодня рассмотрим»,
  «Важно понимать, что», «Данный анализ показывает»
- markdown-обёртка ```json``` или комментарии вне JSON

ОБЯЗАТЕЛЬНО НАЧАТЬ С ЖИВОГО ХУКА — но РАЗНОГО:
- эмоция/наблюдение/сомнение новичка, не сухое введение
- НЕ копируй ОДНУ И ТУ ЖЕ модель из поста в пост.
- ЗАПРЕЩЁННЫЕ ЗАЕЗЖЕННЫЕ ШТАМПЫ (ни в одном из полей не должны встречаться):
  · «рука/руки тянется/тянутся к кнопке»
  · «внутренний хомяк»
  · «мозг уже превращает заголовок в сделку»
  · «заголовок громкий», «громкий заголовок» (как одиночный приём)
  · «новичок» как обращение к читателю
  · «жадность щёлкает», «руки чешутся»
- Используй РАЗНЫЕ образы: усталость, сомнение, любопытство, азарт, сонливость,
  раздражение, наблюдение со стороны, «пролистал и вернулся», «открыл стакан и закрыл»,
  «вспомнил прошлый раз», «отложил телефон», «третий час смотрю на одно и то же», и т.д.
- Каждый пост — НОВАЯ метафора и НОВЫЙ глагол. Сравни мысленно со списком
  `previous_phrases_to_avoid` в user_payload и НЕ повторяйся.

ДЛИНА: 1000–1500 символов всего поста. Абзац 1–3 строки. Telegram читают с телефона.

РАЗРЕШЕНО:
- «может усилить волатильность», «рынок может отреагировать нервно»
- «это фактор риска», «это не причина бежать в сделку»
- «новичку здесь опасно действовать на эмоциях»
- «нужно смотреть реакцию цены, а не только заголовок»
- отделять факт от предположения
- указывать, где именно новичок может ошибиться
- {humor_rules}
- {sarcasm_rules}

Поле `sector` в ответе должно совпадать с sector выбранной новости.

────────────────────────────────────────
ДОПОЛНИТЕЛЬНЫЕ ПРАВИЛА ПО СЕКТОРУ:

sector=political_market_noise (Шум рынка):
- разбираем политический/макро шум ТОЛЬКО как фактор для рынка
  (ликвидность, регулирование, риск-аппетит, доллар, ETF, биржи, стейблкоины)
- НЕ политика ради политики, НЕ партии, НЕ мемы, НЕ скандал без последствий
- если связь с рынком слабая — should_publish=false
- допустимый сарказм: «Громкий заголовок — это не торговый план.»

sector=scam_radar (Скам-радар):
- разбираем явные мошеннические схемы вокруг крипты, AI-ботов, airdrop, фишинга
- цель — защита новичков, ловушка → красные флаги → как не попасться
- ЮРИДИЧЕСКИ БЕЗОПАСНЫЕ ФОРМУЛИРОВКИ:
  * НЕ писать без официального источника: «это точно мошенники», «они украли деньги»,
    «100% скам», «проект преступный», «создатели воры»
  * можно: «есть признаки скама», «похоже на мошенническую схему», «красные флаги»,
    «обещание гарантированной прибыли — опасный признак»,
    «новичку лучше не подключать кошелёк», «без официального источника доверять нельзя»
  * жёстче можно ТОЛЬКО если есть regulator warning / exchange warning /
    security report от известной команды (Chainalysis, SlowMist, PeckShield, CertiK)
- НЕ высмеивать жертв
- допустимый сарказм направлен на схему, не на человека

sector=ai_crypto:
- допустим брендовый комментарий: «ИИ снова пришёл в крипту»,
  «AI-наставник смотрит спокойно, а внутренний хомяк уже ищет кнопку Buy.»
────────────────────────────────────────

JSON-ПОЛЯ:
- human_part — живой хук + что увидел/почувствовал новичок (2–4 короткие фразы).
- hamster_part — мысль «внутреннего хомяка» в кавычках; примерно 50% постов;
                  null если эмоция не уместна (например, если scam_radar и хомяк
                  тут отсутствует, потому что хочется в схему — оставь его).
- mentor_part — AI-наставник: спокойно, строго, слегка саркастично, простыми словами.
- beginner_mistake — ОДНА конкретная ошибка новичка (1 фраза).
- lesson — короткий вывод 1–2 предложения, без призыва к действию.
- question — 1 короткий вопрос аудитории; null если не уместен.
- risk_type — тип риска: market_noise / scam_risk / security_risk / regulation_risk /
              macro_risk / ai_hype / none.
- reader_action — что должен сделать читатель: observe / verify_source /
                  avoid_clicking / improve_security / no_trade / learn.

Если news_batch пустой или все импакты ниже порога — верни:
{{"should_publish": false, "reason": "..."}}

Иначе верни СТРОГО валидный JSON без markdown-обёртки.

ОБЯЗАТЕЛЬНЫЕ поля + расширенные (Stage 13 schema из NEWS STYLE GUIDE):
{{
  "should_publish": true,
  "post_type": "news_analysis",
  "main_news": {{
    "title": "...",
    "source": "...",
    "url": "...",
    "published_at": "..."
  }},
  "specific_title": "Конкретный заголовок поста (НЕ generic)",
  "brief_review": "2–4 предложения сути новости простым языком",
  "key_points": ["3–5 фактов без воды", "...", "..."],
  "why_it_matters": ["2–4 пункта почему это важно", "..."],
  "sector": "ai_crypto|stablecoins|rwa_tokenization|regulation_etf_institutional|security_hacks_scams|depin_infrastructure|defi_restaking|l2_scaling|macro|political_market_noise|scam_radar|memecoins_low_priority|other",
  "risk_type": "market_noise|scam_risk|security_risk|regulation_risk|macro_risk|ai_hype|none",
  "reader_action": "observe|verify_source|avoid_clicking|improve_security|no_trade|learn",
  "image_prompt_hint": "короткий англоязычный hint для генерации картинки или null",
  "impact_score": 0,
  "market_impact": "bullish|bearish|mixed|neutral|uncertain",
  "affected_assets": ["BTC", "ETH"],
  "human_part": "...",
  "hamster_part": "... или null",
  "mentor_part": "...",
  "beginner_mistake": "...",
  "lesson": "...",
  "question": "... или null",
  "hashtags": ["#новости", "#крипта"],
  "short_summary": "8–14 слов для памяти"
}}

ТРЕБОВАНИЯ К РАСШИРЕННЫМ ПОЛЯМ (Stage 12b — обязательны все):
- specific_title: ОБЯЗАТЕЛЬНО конкретный, по сути новости. ЗАПРЕЩЕНЫ generic-заголовки:
  «Новость, которая может двигать рынок», «Новость, за которой стоит следить»,
  «Важная новость», «Срочно», «Сегодня в крипте», «Разбор новости», «Горячая новость».
  Если ты сгенерировал заголовок и он попадает в этот чёрный список — переформулируй,
  публикация будет автоматически заблокирована publish-guard'ом канала.
- brief_review: 2–4 предложения сути новости простым языком. Без воды.
- key_points: РОВНО 3–5 коротких фактов из текста новости (массив). Без выдумок, без обобщений.
- why_it_matters: 2–4 пункта о реальном влиянии (рынок / доверие / сектор / урок новичка).
- human_part / mentor_part / beginner_mistake / lesson — все обязательны и непустые.
- image_prompt_hint: короткий АНГЛИЙСКИЙ prompt для генерации иллюстрации. Всегда возвращай
  непустую строку (15+ символов), даже для скучных новостей. Не описывай реальные лица,
  логотипы или текст — никогда. Стиль канала: editorial illustration, vintage craft paper,
  earthy palette (muted ochre, deep brown, faded teal), no neon. Если затрудняешься —
  опиши абстрактный сектор-симвoл (для security_hacks_scams: «broken padlock and shadow
  reaching toward a vault»; для regulation: «classical scales over stacked ledgers»; и т.д.).

Ровно одно сообщение JSON. Без markdown ``` — иначе пост будет автоматически отклонён.
""".strip()


class NewsAnalyzer:
    def __init__(self, config: NewsConfig, claude: Anthropic, model: str):
        self.cfg = config
        self.claude = claude
        self.model = model

    def analyze(
        self,
        items: list[NewsItem],
        *,
        market_snapshot: Optional[dict] = None,
        previous_phrases_to_avoid: Optional[list[str]] = None,
    ) -> dict:
        """Возвращает распарсенный JSON от Claude. Если Claude решил не публиковать —
        в ответе будет should_publish=false.

        Stage 12f — `previous_phrases_to_avoid`: список «уже использованных» фраз
        из недавних published-постов; Claude должен не повторять ни их формулировки,
        ни их метафоры.
        """
        if not items:
            return {"should_publish": False, "reason": "news_batch пустой"}

        system = build_system_prompt(self.cfg)
        user_payload = {
            "news_batch": [self._compact(it) for it in items],
            "market_snapshot": market_snapshot or {},
            "min_impact_score": self.cfg.news_min_impact_score,
            "humor_level": self.cfg.news_humor_level,
            "sarcasm_level": self.cfg.news_sarcasm_level,
            "previous_phrases_to_avoid": previous_phrases_to_avoid or [],
        }

        resp = self.claude.messages.create(
            model=self.model,
            max_tokens=4000,
            system=system,
            messages=[{"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}],
        )
        raw = (resp.content[0].text or "").strip()
        stop_reason = getattr(resp, "stop_reason", None)
        if raw.startswith("```"):
            raw = raw.strip("`").strip()
            if raw.lower().startswith("json"):
                raw = raw[4:].strip()
        if stop_reason == "max_tokens":
            log.error(
                "NewsAnalyzer: ответ Claude обрезан по max_tokens (len=%d). "
                "Поднимите max_tokens или сократите промпт. Пропускаем публикацию.",
                len(raw),
            )
            return {"should_publish": False, "reason": "claude truncated (max_tokens)"}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            log.error("NewsAnalyzer: Claude вернул не-JSON: %s\n%s", e, raw[:500])
            return {"should_publish": False, "reason": f"claude invalid JSON: {e}"}

    @staticmethod
    def _compact(it: NewsItem) -> dict:
        return {
            "id": it.id,
            "title": it.title,
            "url": it.url,
            "source": it.source,
            "published_at": it.published_at,
            "summary": it.summary[:400],
            "assets": it.assets,
            "category": it.category,
            "sector": it.sector,
            "impact_score": it.impact_score,
        }


# =============================================================================
# helpers
# =============================================================================

def _humor_level_rules(level: str) -> str:
    level = (level or "light").lower()
    if level == "off":
        return "юмор выключен: пиши сухо, без шуток"
    if level == "medium":
        return "юмор допустим средний: одна–две аккуратные шутливые фразы, без цирка"
    return "юмор допустим лёгкий: не больше одной шутливой фразы, аккуратной"


def _sarcasm_level_rules(level: str) -> str:
    level = (level or "light").lower()
    if level == "off":
        return "сарказм выключен"
    if level == "medium":
        return "сарказм допустим умеренный: без перехода на личности, без токсичности"
    return "сарказм допустим лёгкий: 0–1 фраза, строго без токсичности"
