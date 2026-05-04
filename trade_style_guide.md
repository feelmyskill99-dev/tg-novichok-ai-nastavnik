# TRADE STYLE GUIDE — Депозит под надзором ИИ

## ЦЕЛЬ

Сделки в канале — это не сигналы, а учебный дневник.

Главная задача:

- показать план;
- объяснить риск;
- показать ошибку новичка;
- сохранить доверие;
- не подталкивать аудиторию повторять сделку.

---

## ПРИНЦИП

Писать не так:

> “Открываем long BTC.”

Писать так:

> “Учебная сделка: проверяю торговый план. Не повторять. Смотрим, где идея ломается.”

---

## ЗАПРЕЩЁННЫЕ ФРАЗЫ

- сигнал;
- точный вход;
- залетаем;
- покупаем;
- шортим;
- гарантия;
- забираем прибыль;
- иксы;
- киты точно входят;
- повторяйте;
- уверен на 100%.

---

## РАЗРЕШЁННЫЕ ФРАЗЫ

- учебная сделка;
- paper-сделка;
- confirm-сделка;
- торговый план;
- сценарий;
- гипотеза;
- если сценарий сломается;
- риск ограничен;
- не повторять;
- дневник обучения.

---

## PAPER / CONFIRM / LIVE

### Paper

Виртуальная сделка. Деньги не трогаются.

Подходит для:

- обучения;
- бэктеста;
- разбора ошибок;
- контента в канал.

### Confirm

Реальная сделка, но только после ручного подтверждения владельца.

Правила:

- Telegram inline-кнопка;
- таймаут подтверждения;
- повторная проверка риска перед approve;
- не ставить ордер без TP/SL;
- не публиковать в канал автоматически.

### Live

Полностью автоматическая торговля. По умолчанию отключена.

Не включать без отдельного решения и серии успешных confirm-сделок.

---

## CONFIRM TRADE MESSAGE TEMPLATE

```html
📒 <b>[CONFIRM REAL TRADE]</b>

⚠️ Это реальная сделка на Gate.io Futures.
Ордер будет выставлен только после подтверждения.

<b>Asset:</b> {symbol}
<b>Side:</b> {side}
<b>Entry:</b> {entry}
<b>Stop Loss:</b> {stop_loss}
<b>Take Profit:</b> {take_profit}
<b>Leverage:</b> x{leverage}
<b>Margin mode:</b> isolated
<b>Risk:</b> {risk_amount} USDT
<b>Notional:</b> {notional} USDT
<b>Contracts:</b> {contracts}
<b>RR:</b> {risk_reward}

<b>Reason:</b>
{reason}

<b>Beginner risk:</b>
{beginner_risk}

<b>Safety checks:</b>
- whitelist: {whitelist_status}
- leverage_cap: {leverage_status}
- daily_loss: {daily_loss_status}
- open_positions: {open_positions_status}
- sl_tp: {sl_tp_status}
- min_balance: {min_balance_status}
- contracts: {contracts_status}

Trade ID: {trade_id}
Confirm timeout: ждём кнопку, потом expired_confirmation

Это не финансовый совет. Подтверждение означает, что ты сам принимаешь риск. Реальный ордер на Gate.io будет выставлен только после нажатия кнопки.
```

Важно: не писать “Открыта”, пока реальный order не создан.

Статусы:

- awaiting_confirmation — ждёт кнопку;
- approved — подтверждено;
- entry_order_submitted — entry отправлен;
- entry_filled — entry исполнен;
- protection_orders_submitted — TP/SL выставлены;
- active — позиция активна и защищена;
- failed — ошибка;
- rejected — отклонено;
- expired_confirmation — истёк таймаут.

---

## OPEN TRADE POST TEMPLATE

```html
📍 <b>Учебная сделка открыта</b>

Смотрю на график и ловлю знакомое чувство:
“а может, надо было зайти раньше?”

Но сегодня сначала план. Потом вход.

📊 <b>План сделки</b>
Актив: {symbol}
Направление: {side}
Entry: {entry}
SL: {stop_loss}
TP: {take_profit}
Плечо: x{leverage}
Риск: {risk_percent}%
RR: {risk_reward}

🐹 <b>Внутренний хомяк</b>
“Ну если идея нормальная, может плечо побольше?”

🤖 <b>AI-наставник</b>
Если идея хорошая, ей не нужно x20, чтобы выглядеть умной.
Главная задача сейчас — не угадать рынок, а проверить план и не трогать стоп руками.

⚠️ <b>Ошибка новичка</b>
Думать, что маленький депозит разрешает большой риск.

📌 <b>Урок</b>
Сделка начинается не с кнопки Buy/Sell.
Сделка начинается с ответа на вопрос: где я признаю, что ошибся?

Не финсовет. Это дневник обучения и AI-разбор.

#честный_путь #риск_менеджмент #BTC
```

---

## CLOSED TP TEMPLATE

```html
✅ <b>Учебная сделка закрылась по TP</b>

План отработал.

И, конечно, внутренний хомяк уже проснулся:
“А если бы поставили больше? А если бы плечо x10?”

🤖 <b>AI-наставник</b>
Вот именно здесь многие новички ломают себе дисциплину.

Правильный вывод после плюсовой сделки — не “надо было рискнуть сильнее”.
Правильный вывод — “план сработал, потому что риск был заранее ограничен”.

📊 <b>Итог</b>
Entry: {entry}
Exit: {exit}
Результат: {pnl}
R: {r_multiple}

⚠️ <b>Ошибка новичка</b>
После удачной сделки решить, что ты стал умнее рынка.

📌 <b>Урок</b>
Один TP не делает меня трейдером.
Но один соблюдённый план делает меня менее хомяком.

Не финсовет. Это дневник обучения и AI-разбор.

#честный_путь #дисциплина #BTC
```

---

## CLOSED SL TEMPLATE

```html
📉 <b>Учебная сделка закрылась по стопу</b>

Неприятно.
Но депозит жив — и это уже не провал.

🐹 <b>Внутренний хомяк</b>
“Может, надо было убрать стоп? Цена же могла развернуться…”

🤖 <b>AI-наставник</b>
Вот так стоп превращается в надежду, а надежда — в ликвидацию.

Стоп не означает, что ты плохой трейдер.
Он означает, что сценарий не сработал, и ты вышел там, где заранее обещал себе выйти.

📊 <b>Итог</b>
Entry: {entry}
Exit: {exit}
Результат: {pnl}
R: {r_multiple}

⚠️ <b>Ошибка новичка</b>
Считать стоп поражением, а не частью системы.

📌 <b>Урок</b>
Маленький контролируемый минус лучше, чем большой эмоциональный слив.

Не финсовет. Это дневник обучения и AI-разбор.

#ошибки_новичка #стоп_лосс #BTC
```

---

## EXPIRED SETUP TEMPLATE

```html
⌛ <b>Сделка не открылась</b>

Цена так и не дошла до моей зоны входа.

И да, было желание подвинуть entry поближе к рынку.
Просто чтобы “ну хоть как-то войти”.

🤖 <b>AI-наставник</b>
Если ты двигаешь вход за ценой, это уже не план.
Это догонялки.

Не каждая идея обязана стать сделкой.
Иногда рынок просто не дал нормальную цену — и это тоже ответ.

📌 <b>Урок</b>
Пропущенная сделка не минус.
А вот вход вдогонку без плана — уже кандидат.

Не финсовет. Это дневник обучения и AI-разбор.

#дисциплина #не_будь_хомяком #BTC
```

---

## TRADE VISUAL SYSTEM

Основная стратегия:

- generated trade-card — для анализа и обучения;
- Gate.io screenshot — для доверия, proof-of-use и партнёрской связки;
- TradingView-style chart — для рыночной логики.

Gate.io screenshot не должен быть единственным источником визуала.

---

## TRADE-CARD ELEMENTS

На картинке показывать:

- Symbol;
- Side;
- Status;
- Entry;
- Stop Loss;
- Take Profit;
- Current Price;
- Liquidation, если есть;
- Leverage;
- Risk %;
- RR;
- Position size;
- PnL, если закрыта;
- R-multiple, если закрыта;
- Duration, если доступна.

Линии:

- Entry — blue;
- TP — green;
- SL — red;
- Liquidation — orange;
- Current Price — gray/white.

Нижняя подпись:

```text
Депозит под надзором ИИ
Не финсовет • Дневник обучения
```

---

## GATE.IO SCREENSHOT ROLE

Использовать Gate.io screenshots:

- как подтверждение фактической торговли;
- в гайдах по интерфейсу;
- при открытии/закрытии confirm-сделок;
- в onboarding.

Фраза:

```text
На графике — логика сделки. На скрине Gate.io — фактическое исполнение.
```

Manual screenshot flow:

1. Бот присылает trade_id.
2. Владелец отправляет скрин с подписью `/attach_gate_screenshot <trade_id>`.
3. Бот сохраняет в `outputs/gate_screenshots/`.
4. Бот связывает с trade_id.

---

## GATE FUTURES SAFETY NOTES

Gate.io futures amount должен быть в контрактах, а не fractional BTC.

Для BTC/USDT:USDT:

- брать `market["contractSize"]`;
- считать raw_contracts = notional_usdt / (entry_price * contractSize);
- contracts = floor(raw_contracts);
- если contracts < min amount — отклонять до approve;
- показывать contracts в confirm preview.

Не пытаться менять isolated/cross margin, если по symbol уже есть открытая позиция.

Перед approve проверять:

- no existing position for symbol;
- no pending live trade for symbol;
- contracts >= min amount;
- notional >= minimum contract notional;
- leverage <= HARD_MAX_LEVERAGE;
- isolated mode only if no existing position.

---

## REVIEW RULES FOR TRADES

В канал автоматически не публиковать реальные сделки, пока это не разрешено явно.

По умолчанию:

- OWNER_CHAT_ID получает preview;
- канал не трогается;
- publish только после approve/review flow.

---

## CLI CHECKS

Полезные команды:

```bash
python bot.py --confirm-trade-now
python bot.py --live-reconcile-now
python bot.py --kill-switch-status
python bot.py --render-last-trade-visual
python bot.py --render-trade-visual <trade_id>
```
