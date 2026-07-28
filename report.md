# Max Algos — Platform Report

A self-hosted algorithmic trading platform for Indian markets (NSE/BSE/NFO/BFO/CDS/MCX) plus crypto derivatives, built as **four products in one instance**: a unified broker API, an in-browser Python strategy host, a no-code visual workflow builder, and a 12-tool options analytics suite — all sharing one broker session and one live-data pipeline..

---

## 1. What the platform actually is

| Surface | Route | Purpose |
|---|---|---|
| Unified Broker API | `/api/v1/` | One REST API that 27 different brokers speak underneath — external tools (TradingView, Amibroker, ChartInk, Excel, Python scripts, MCP clients) integrate once, work with any connected broker |
| Python Strategy Host | `/python` | Paste a Python script into a browser editor, schedule it on IST times, run it in a fully isolated subprocess, watch its logs live |
| Flow (No-Code Builder) | `/flow` | Drag-and-drop node graph — market data → indicators → conditions → order execution — no code required |
| Options Trading Suite | `/tools` | 12 analytical tools: Option Chain, Strategy Builder, IV Smile, Max Pain, Vol Surface, GEX, OI Tracker, Straddle Chart, and more |

Every surface executes through the same broker session, the same WebSocket feed, and (for webhook-driven strategies) the same signal-execution engine — so a position opened from the Python host is visible in the Strategy Builder's positions panel, and a strategy built visually can be monitored from the same dashboard as a hand-written script.

---

## 2. Options strategies — all 38 templates

The Strategy Builder's template library expresses every strategy as a set of legs with strikes given as **offsets from ATM in strike-steps** (e.g. NIFTY's step is 50 — an offset of `+2` means two strikes above ATM, i.e. 100 points OTM for a call). Picking a template resolves those offsets against the live option chain, so the same template produces the correct real strikes regardless of where the market currently sits.

### Bullish (9) — used when you expect the underlying to rise

| Strategy | Structure | Why you'd use it |
|---|---|---|
| **Long Call** | Buy 1 ATM/OTM call | Simplest bullish bet. Unlimited upside, loss capped at premium paid. Use for a strong directional view with defined risk. |
| **Short Put** | Sell 1 ATM/OTM put | Collect premium betting the market stays above the strike. Works in flat-to-bullish markets; risk is large if the market falls hard. |
| **Bull Call Spread** | Buy ATM call, sell OTM call (+2 steps) | Caps both profit and loss — cheaper than a naked long call, sacrifices unlimited upside for a lower cost of entry. |
| **Bull Put Spread** | Sell ATM put, buy OTM put (-2 steps) | A net-credit version of the same view — collect premium up front, capped loss below the long put. |
| **Call Ratio Backspread** | Sell 1 ATM call, buy 2 OTM calls (+2) | Small net credit or debit; designed to profit hard from a sharp rally while only small losses accrue on a modest move. |
| **Long Synthetic** | Buy ATM call + sell ATM put (same strike) | Replicates a long futures position using options — unlimited upside and unlimited downside, same delta profile as owning the underlying. |
| **Range Forward** | Sell OTM put (-2), buy OTM call (+2) | A "collar" built for a bullish view: limited downside from the short put, unlimited upside from the long call, usually near-zero net cost. |
| **Bullish Butterfly** | Buy ATM call, sell 2 calls (+2), buy 1 call (+4) | Defined, cheap risk that pays out best if the market rallies to land exactly at the body strike — a precision bullish bet, not a broad one. |
| **Bullish Condor** | Buy call, sell call (+1), sell call (+3), buy call (+4) | Like the butterfly but with a wider flat profit zone instead of a single peak — trades peak profit for a larger margin of error. |

### Bearish (9) — used when you expect the underlying to fall

| Strategy | Structure | Why you'd use it |
|---|---|---|
| **Short Call** | Sell 1 ATM/OTM call | Collect premium betting the market stays below the strike. Mirror of Short Put; large risk if the market rallies hard. |
| **Long Put** | Buy 1 ATM/OTM put | Simplest bearish bet, capped loss, large profit potential on a sharp fall. |
| **Bear Call Spread** | Sell ATM call, buy OTM call (+2) | Net-credit bearish trade with capped risk — the classic income strategy for a mildly bearish/flat view. |
| **Bear Put Spread** | Buy ATM put, sell OTM put (-2) | Capped-cost bearish debit spread — cheaper than a naked put, caps the payout too. |
| **Put Ratio Backspread** | Sell 1 ATM put, buy 2 OTM puts (-2) | Mirror of the call backspread — profits hard from a sharp fall, small loss on a modest move. |
| **Short Synthetic** | Sell ATM call + buy ATM put | Replicates a short futures position with options — unlimited profit on a fall, unlimited loss on a rally. |
| **Risk Reversal** | Buy OTM put (-2), sell OTM call (+2) | Bearish collar — profits on the downside, exposed to unlimited loss if the market rallies through the short call. |
| **Bearish Butterfly** | Buy ATM put, sell 2 puts (-2), buy 1 put (-4) | Precision bearish bet — best payout if the market falls to land exactly at the body strike. |
| **Bearish Condor** | Buy put, sell put (-1), sell put (-3), buy put (-4) | Wider, more forgiving version of the bearish butterfly. |

### Non-directional (20) — used when your view is about volatility or a range, not direction

| Strategy | Structure | Why you'd use it |
|---|---|---|
| **Long Straddle** | Buy ATM call + ATM put | Profits from a big move in *either* direction — the classic "something big is about to happen but I don't know which way" trade. |
| **Short Straddle** | Sell ATM call + ATM put | Bets the market stays pinned near the strike — high premium collected, unlimited risk on a big move either way. |
| **Long Strangle** | Buy OTM put (-2) + OTM call (+2) | Cheaper long-volatility trade than a straddle, but needs a bigger move to profit. |
| **Short Strangle** | Sell OTM put (-2) + OTM call (+2) | Cheaper-premium version of the short straddle with a wider profit zone — still unlimited risk on a big move. |
| **Jade Lizard** | Sell OTM put (-2), sell call spread (+2/+4) | Constructed so there's *no upside risk at all* if the collected credit exceeds the call spread's width — a popular "no-loss-on-one-side" income trade. |
| **Reverse Jade Lizard** | Sell OTM call (+2), sell put spread (-2/-4) | Mirror image — no downside risk if credit exceeds the put spread's width. |
| **Call Ratio Spread** | Buy 1 ATM call, sell 2 OTM calls (+2) | Peak profit sits at the short strike; unlimited loss above it — used when you expect a *moderate* rally, not a runaway one. |
| **Put Ratio Spread** | Buy 1 ATM put, sell 2 OTM puts (-2) | Mirror of the above for a moderate decline. |
| **Batman Strategy** | Call ratio spread (wide, +10/+15) + Put ratio spread (wide, -10/-15) | Two small profit peaks ("ears") straddling spot with unlimited loss on both wings from the extra short legs — a specialist, high-risk structure. |
| **Long Iron Fly** | Short ATM straddle, wings at ±2 | Max profit if the market pins exactly at ATM — defined-risk version of a short straddle. |
| **Short Iron Fly** | Long ATM straddle, wings sold at ±2 | Profits on a big move either way; max loss is at ATM — defined-risk version of a long straddle. |
| **Double Fly** | Two iron butterflies (8 legs), bodies at -8/+8 | Two profit peaks, one below spot and one above — used to bracket two likely landing zones. |
| **Long Iron Condor** | Bull put spread (-4/-2) + bear call spread (+2/+4) | The signature defined-risk range trade — profits if the market stays inside a band, capped loss either way. |
| **Short Iron Condor** | Reverse of the above | Profits on a big move either way; caps the loss if the market instead pins in the middle. |
| **Double Condor** | Call condor + put condor at different strikes | Two wide flat profit plateaus flanking spot — a wider, more forgiving cousin of the double fly. |
| **Call Calendar** | Sell near-expiry ATM call, buy far-expiry ATM call | Profits from the near leg's faster time decay (theta) while the far leg holds its value — a time-decay play, not a directional one. |
| **Put Calendar** | Sell near-expiry ATM put, buy far-expiry ATM put | Put-side equivalent of the call calendar. |
| **Diagonal Calendar** | Sell near ATM call, buy far OTM call (+2) | A calendar with a mild directional tilt built in via the strike offset. |
| **Call Butterfly** | Buy call (-2), sell 2 calls (ATM), buy call (+2) | Classic defined-risk butterfly centred at ATM — best payout if the market pins exactly there. |
| **Put Butterfly** | Buy put (+2), sell 2 puts (ATM), buy put (-2) | Put-side mirror of the call butterfly. |

**How to choose:** direction (bullish/bearish/neutral) narrows the list to one of the three tables above; risk appetite then picks the row — naked long/short options for maximum payoff with defined or unlimited risk, spreads for capped risk and lower cost, butterflies/condors for precision bets on where the market lands, calendars for pure time-decay plays.

---

## 3. Equity trade templates (12)

Unlike the options templates above, these have no strikes to resolve — picking one just pre-fills the equity order form's order type and a suggested Stop-Loss / Target percentage.

| Template | Side | Use case | Order type | SL % | Target % |
|---|---|---|---|---|---|
| Momentum Buy | BUY | Ride an already-strong up-move, tight stop | Market | 1.0 | 3.0 |
| Breakout Entry | BUY | Enter on a confirmed break above resistance | Limit | 1.5 | 4.0 |
| Pullback Buy | BUY | Buy a shallow dip within an uptrend | Limit | 1.5 | 3.5 |
| Swing Long | BUY | Multi-day positional hold, wider stop | Limit | 3.0 | 8.0 |
| Intraday Scalping | BUY | Quick in-and-out on small fast moves | Market | 0.4 | 0.8 |
| VWAP Reversal | BUY | Enter on reversion back toward VWAP | Limit | 1.0 | 2.0 |
| Moving Average Cross | BUY | Enter on a fast/slow MA crossover | Market | 2.0 | 5.0 |
| RSI Reversal | BUY | Enter as RSI exits oversold | Limit | 1.5 | 3.0 |
| Support Bounce | BUY | Buy a bounce off tested support | Limit | 1.5 | 3.0 |
| Resistance Breakout | BUY | Buy a confirmed break above resistance | Limit | 1.5 | 4.0 |
| Gap Up Strategy | BUY | Trade continuation after a bullish gap | Market | 1.5 | 3.0 |
| Gap Down Short | SELL | Trade continuation after a bearish gap | Market | 1.5 | 3.0 |

Note: 11 of 12 templates are long-only; **Gap Down Short is currently the only short-side template** — there's no dedicated short-side scalping/swing/momentum equivalent yet.

Target/Stop-Loss on equity legs are placed as a real broker **GTT (Good Till Triggered) OCO order** once the entry fills — see §6. Trailing Stop-Loss is a UI field only; no broker or backend service currently tracks price to ratchet a stop (explicitly disabled with a "Soon" label, not faked).

---

## 4. Full feature inventory

### Trading core
Dashboard · Positions · Order Book · Trade Book · Holdings (auto-hidden for crypto brokers, which have no holdings concept) · Symbol Search · API Key management · TradingView/GoCharting chart integrations · PnL Tracker · Sandbox trading + its own PnL view · Analyzer (raw request/response inspection) · Leverage config (crypto-only, gated by broker capability) · WebSocket depth test pages

### Options Trading Suite (12 tools under `/tools`)
1. **Option Chain** — live CE/PE chain centered on ATM with real-time LTP
2. **Strategy Builder** — the visual multi-leg builder driving all 38 templates above, plus a dedicated Equity mode (templates, order form, live Trade Preview with R:R and bracket meter)
3. **IV Chart / Greeks** — implied volatility plus delta/theta/gamma/vega per option
4. **OI Tracker** — Open Interest by strike, bar chart
5. **Max Pain** — the strike where option writers' aggregate loss is minimized, plotted in ₹ Crores
6. **Straddle Chart** — live ATM straddle premium vs spot vs synthetic future over time
7. **Custom Straddle / Straddle PnL Simulator** — build a custom multi-leg straddle-like position and simulate its payoff
8. **Vol Surface** — implied volatility across Strike × Expiry
9. **GEX Dashboard** — Net Gamma Exposure by strike (dealer positioning / gamma walls)
10. **IV Smile** — implied volatility vs strike for a single expiry
11. **OI Profile** — Open Interest build-up/unwind over intraday time
12. **Camarilla Pivot Calculator** — 8 Camarilla levels (H5→L5) computed from the prior day's real range, each with a trading note (e.g. H5: "Super breakout target level," H3: "Price reversal resistance — go short here in range-bound markets")

Plus: Marketplace, Analytics, Deployments — all reachable from the same Options Tools shell.

### Strategy management (webhook-driven)
Strategy registry with search/filter · New Strategy wizard (guided creation with a risk-acknowledgment gate for unlimited-risk templates) · Strategy Templates gallery · Backtest logs · per-strategy symbol configuration · Webhooks Guide

### Python Strategy Host
Upload/Start/Stop/Schedule/Delete strategies from a browser-based CodeMirror editor. Each strategy runs in its **own OS process** for complete isolation (Windows/Linux/macOS), scheduled via IST-aware cron triggers. The host injects the API key, exchange context, strategy ID, and WebSocket URL as environment variables, so a script written for the hosted environment needs zero changes to also run standalone.

### Flow — No-Code Visual Builder
A JSON node-graph editor with ~48 node types across seven categories: **Orders** (place/modify/cancel/basket/split), **Market data** (quotes, depth, option chain, history, symbol resolution), **Account data** (order book, positions, holdings, funds, margin), **Control flow** (delay, wait-until, variables, math, AND/OR/NOT logic gates), **Alerts/integration** (Telegram, HTTP webhook, price alerts), **Conditions** (position/fund/price/time checks), and **Live subscriptions** (LTP/quote/depth streaming). Execution is depth- and visit-limited (max depth 100, max 500 node visits per run) with per-workflow locking to prevent re-entrant runs.

### MaxHook — unified signal front door
One connections list that merges two separate backends (the generic webhook engine used by TradingView-style sources, and Chartink's own engine) into a single UI — connect an external signal source, get a webhook URL, configure symbol mappings and an intraday execution window, toggle active/inactive.

### Sandbox trading mode
₹1 Crore virtual capital in a fully separate database, realistic margin/leverage simulation, auto square-off aligned to real exchange timings, complete isolation from live trading — the safe place to test a strategy before it touches real money.

### Action Center (order approval)
Two execution modes, chosen per user: **Auto** executes every order immediately (personal trading); **Semi-Auto** routes every order into a `PendingOrder` queue with full audit fields (approver, timestamp, rejection reason) until a human approves or rejects it — built for managed-account use where someone other than the strategy author must sign off on each trade.

### Real-time architecture
Broker WebSocket adapters normalize each broker's proprietary feed → a ZeroMQ pub/sub bus decouples the feed from client delivery → a unified WebSocket proxy server manages client subscriptions and throttles slow clients. Capacity: 1000 symbols × 3 connections = 3000 symbols per broker by default. App-level events (order updates, cache-loaded, analyzer results) ride a parallel Flask-SocketIO channel.

### System & Admin
Health Monitor · Logs (general/live/security/traffic/latency) · Master Contract browser · Profile · Telegram and WhatsApp alert integrations · Admin console: Freeze Quantities, Market Holidays, Market Timings, Diagnostics, Remote MCP config, User Management, Payment Settings, Email Settings.

---

## 5. Supported brokers — 27 integrations

Every broker below ships a WebSocket streaming adapter (live data is universal). **GTT (bracket Target/Stop-Loss) orders currently only work on Zerodha and Dhan** — every other broker will return a clear "not supported yet" error if a GTT order is attempted, rather than silently failing.

### Discount / retail brokers (16)
Standard NSE/BSE/NFO/BFO coverage, most also covering currency (CDS) and commodity (MCX) derivatives.

| Broker | GTT | Notable coverage |
|---|---|---|
| **Zerodha** | ✅ | Widest coverage of any broker — only one with `GLOBAL_INDEX` (US30, Japan225, HangSeng, GIFT Nifty) and NSE commodities (`NCO`). Reference implementation. |
| **Dhan** | ✅ | Reference implementation. |
| Dhan Sandbox | — | Dhan's separate paper-trading plugin |
| Upstox | — | Only other broker besides Zerodha with `GLOBAL_INDEX` |
| Angel One | — | Reference implementation |
| Fyers | — | |
| Flattrade | — | |
| Shoonya | — | |
| AliceBlue | — | |
| Zebu | — | No BSE index feed |
| 5paisa | — | |
| Firstock | — | Narrowest coverage — no currency or commodity segments |
| DefinedGe Securities | — | |
| Arrow | — | |
| BNR Securities | — | |
| IndMoney | — | No currency/commodity |
| Pocketful | — | No currency segment |

### Full-service / institutional brokers (10)
Several are white-labeled on the XTS institutional trading framework.

| Broker | GTT | Notes |
|---|---|---|
| Motilal Oswal | — | |
| Sharekhan | — | No index-only segments |
| IIFL | — | |
| IIFL Capital | — | Separate plugin from IIFL, broader currency coverage |
| Compositedge | — | |
| 5paisa (XTS) | — | Distinct plugin from standard 5paisa |
| Jainam XTS | — | |
| RMoney (XTS) | — | |
| Wisdom Capital (XTS) | — | |
| IBulls | — | No currency segment |

### Crypto exchanges (1)
| Broker | GTT | Notes |
|---|---|---|
| Delta Exchange | — | Crypto derivatives (futures & options). The **only** broker with leverage configuration — this is what gates the platform's `/leverage` page. Also enforces SEBI-adjacent static-IP whitelisting on its own side. |

---

## 6. Real order placement — what's actually wired

Two execution paths exist, both go through the same backend service layer (so both automatically respect the Live/Sandbox toggle and the Auto/Semi-Auto Action Center gate — no path bypasses either):

- **Entry orders** — fully live: `/placeorder`, `/placeordermulti`, `/basketorder`, `/basketordermulti`. Used everywhere an order is placed, including the Strategy Builder's Execute dialog.
- **Target / Stop-Loss (equity)** — wired this session onto the backend's existing GTT endpoint. After an equity entry order fills, if the leg has a Target and/or Stop-Loss set, the platform automatically places a real broker-side GTT bracket (OCO if both are set, SINGLE if only one). Hard constraints, all surfaced honestly in the UI rather than hidden:
  - Requires product **CNC or NRML** — MIS is blocked at the form level before an order is even placed, since GTT doesn't support intraday products.
  - Only works on **Zerodha and Dhan** — any other broker's failure is shown per-symbol, not silently dropped.
  - **Does not work in Sandbox mode** at all — detected automatically, with a specific message rather than a wasted network call.
  - Multi-broker execution skips bracket-attach entirely (GTT capability barely exists across brokers) — shown as an inline warning listing exactly which symbols got no protection.
- **Trailing Stop-Loss** — UI field only, visibly disabled with a "Soon" label. No broker and no backend service anywhere in this platform currently tracks live price to ratchet a stop — this would require a new polling scheduler service, which is a deliberate, scoped-out future build rather than something faked client-side (a fake trailing stop would silently stop protecting the position the moment the browser tab closes).

---

## 7. Compliance handling

### Platform-level security model
- **Single user per deployment, self-hosted** — no multi-tenant surface, no privilege-escalation risk between users; whoever controls the server controls everything.
- **Unique secrets per install** — `APP_KEY` and `API_KEY_PEPPER` are generated fresh via cryptographically secure randomness on every install, never shared defaults.
- **SEBI static-IP mandate** (effective April 1, 2026): transactional orders require the broker to whitelist the server's outbound IP. This makes stolen broker credentials useless from an attacker's own machine — they can only be used by routing through this server itself, which narrows (but doesn't eliminate) the attack surface.
- Indian broker session tokens expire daily near 3:00 AM IST; the platform's session management is aligned to that schedule automatically.
- The MCP server is local-only (stdio to Claude Desktop/Cursor/Windsurf) — never remotely reachable.

### SEBI Algorithmic Trading Circular — formal gap audit exists
There is a dated internal audit (`docs/audit/sebi-algo-trading-compliance-2026-07.md`, 2026-07-16) against SEBI's Feb 2025 circular on retail algo trading (effective Aug 1, 2025), treating this platform as an "Algo Provider" with the broker as a separately regulated party. It is honest about what's fixed versus what's still open:

**Actually fixed and shipped:**
- **Unique per-order audit identifiers** — every order now carries a fresh UUID-suffixed tag (`utils/order_tag.py`), replacing what used to be identical hardcoded tags across Zerodha, Motilal, Nubra, and Upstox orders (some were literally the API docs' placeholder text).
- **Opt-in two-factor authentication for API key generation** — a user can now require a fresh TOTP code before minting or rotating their API key. (Not mandatory by default — that's a deliberate rollout decision, not an oversight.)
- **5-year audit trail retention guard** — the order log table now has an explicit `MIN_RETENTION_YEARS = 5` with a hard assertion that blocks any code path from deleting a record before that window closes.

**Honestly documented as still open** (not silently skipped):
- **Static IP whitelisting** is enforced only by the broker's own systems, not by this codebase — there's unused dead code for it in one broker module (`dhan_sandbox`) that was never wired up.
- **OAuth-only broker authentication** — roughly a third of the 27 brokers still use password/TOTP login rather than OAuth. Fixing this would mean dropping broker support entirely for those integrations, a real product tradeoff left for a deliberate decision rather than made silently.
- **Order-rate threshold monitoring** — only generic per-IP HTTP rate-limiting exists today; SEBI's actual requirement (detect a threshold breach, categorize the activity as algorithmic, register it with the Exchange) needs a real number from each broker's ISF and an Exchange-side registration channel that doesn't exist in this codebase yet.

### Pre-trade risk warnings — UI acknowledgment, not a backend gate
The Strategy Wizard shows a hard confirmation dialog for any unlimited-risk strategy template, referencing SEBI's SPAN margin check requirement. This is genuinely just a warning the user must click through — there is **no backend SPAN-margin validation** wired to it. Real margin sufficiency is only ever checked wherever the broker's own order API happens to reject an order at execution time. This is worth knowing clearly: the dialog informs, it doesn't enforce.

### Freeze quantity — real NSE-mandated limits, actively enforced
NSE mandates a maximum quantity per single order for F&O contracts; anything larger must be split into multiple orders. This platform has real, working code for it: an admin-editable table of freeze quantities per symbol (with CSV bulk upload), and a live order-splitting service that automatically breaks an oversized order into the correct number of child orders at request time. Currently NFO uses real NSE-published freeze values; BFO/CDS/MCX default to a placeholder value of 1 pending real data for those segments — documented as a known gap, not hidden.

### Market holiday calendar — operational, feeds compliance-adjacent timing
A real holiday calendar (trading holidays, settlement holidays, special sessions, per-exchange) actively gates the Python Strategy Host's scheduling and drives Sandbox's exchange-aligned auto square-off timing — so a scheduled strategy won't fire on a day the market is actually closed, and sandbox positions square off at the real exchange time rather than a hardcoded guess.

### Action Center — a product control, not a SEBI mandate
The Auto/Semi-Auto order-approval split is real, fully wired, and audit-complete (who approved, when, why rejected) — but it exists for **managed-account use cases**, not because SEBI requires a human-approval layer on a single-user platform. Worth distinguishing from the SEBI-driven items above.

### Honest summary table

| Control | Actually enforced in code? |
|---|---|
| Unique per-order audit tag | **Yes** |
| 5-year audit log retention | **Yes** |
| 2FA for API key generation | **Yes — opt-in only, not mandatory by default** |
| Freeze quantity + auto order-splitting | **Yes — NFO real data; BFO/CDS/MCX use a placeholder** |
| Market holiday calendar | **Yes — feeds real scheduling/square-off decisions** |
| Action Center order approval | **Yes — but a product feature, not a SEBI requirement** |
| Static IP whitelisting | **No — broker-enforced only, unused dead code exists** |
| OAuth-only broker authentication | **No — ~9 of 27 brokers still use password/TOTP** |
| Order-rate threshold → Exchange registration | **No — only generic IP rate-limiting exists** |
| Pre-trade SPAN margin check | **No — confirmation dialog only, no backend gate** |

---

## 8. One-line takeaway

Max Algos gives you one broker session that powers four different ways to trade — hand-built visual strategies across 38 real option structures, hosted Python scripts, no-code automation flows, and raw API access — backed by real (not simulated) order placement, a working GTT bracket system for equity Target/SL, and a compliance posture that's honestly a mix of shipped engineering fixes and clearly-documented open items rather than either full compliance or hidden gaps.
