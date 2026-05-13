# Option Panda — Data Liveness Health Check

This document is the acceptance-criteria contract for "every data element in the scanner is dynamic, not a placeholder, and not stale." It is the source of truth for the runtime checks wired into `window.opHealthCheck()` and the API-tab UI panel.

## Status legend

| Status | Meaning |
|---|---|
| `pass` | Element is rendering live data inside an acceptable freshness window. |
| `warn` | Element has data but it's stale, partial, or sourced from a cached fallback. |
| `fail` | Element is missing, frozen at a known placeholder, or carrying obviously-wrong data. |
| `n/a` | Element is conditionally rendered and currently not on screen (no scan run, no positions, etc.). Not an error. |
| `error` | Predicate threw — surfaces real bugs in the check or in upstream state. |

## Severity legend

| Severity | Used for |
|---|---|
| `critical` | Element drives a trading decision (score, signal, P&L, contract pick, buying power). A `fail` here means stop and fix. |
| `important` | Element informs a trading decision but is not directly actionable on its own (indicator value in detail pane, sector tag, % change). |
| `info` | Cosmetic / contextual (clock, version, sub-counts). A `fail` is logged but non-blocking. |

## How to run

Browser console:
```js
window.opHealthCheck();        // runs everything, prints console.table, returns array
window.opHealthCheck('sc');    // filter to one tab (sc/bs/pos/pf/order/gex/ind/news/al/api/wl/hdr)
```
UI:
- Open the **API tab → DATA HEALTH CHECK** card → click **▶ RUN HEALTH CHECK**. Results render inline as a red/amber/green table.

Claude-managed:
- After a scan, ask Claude to run `opHealthCheck()` via console and report fails/warns. Claude owns keeping the checks current as the scoring engine evolves.

---

## Tab: Header / ribbon

| Element | Source | Acceptance |
|---|---|---|
| Clock | computed (`Date.now()`) | Updates every 1s; matches `HH:MM:SS (AM\|PM) CT`. |
| Version chip | const `APP_VERSION` | Matches `/^v\d+\.\d+\.\d+/`. |
| SPY / QQQ / DIA / IWM / VIX / GLD / SPX badges | Tradier `/v1/markets/quotes` | Price is a finite number > 0; % change is signed and not `(--)`. |
| Scan status pill | computed from `G._scanFinished` / `G.scanRunning` | Hidden until first scan; then shows `SCAN:` followed by a state word. |
| Auto-scan state | `localStorage:rrjcar_auto_scan_*` | Text is `ON` or `OFF` (not empty). |
| TRADE token pill | `window._tradeToken` + `sessionStorage` | Text includes `locked` or `ready`. |
| BP peek FAB | `G.lastBP.option` from `Tradier /v1/accounts/<id>/balances` | Numeric, > 0, refreshed within 5 min. |

## Tab: Scan (`sc`)

| Element | Source | Acceptance |
|---|---|---|
| Last-scan timestamp (`#sc-last-scan`) | `localStorage:op_cache_scan_ts` | Not `Last scan: never`; parses to a real date; `< 24h` old. |
| Data-status chip (`#sc-data-status`) | computed (`indEnriched` + `fmpEnriched`) | Text mentions `complete` OR specifies the gap; never empty after scan completes. |
| Category strip counts (HC / Breakout / Momentum / Best ITM / Pre-Post) | computed via `_matchesPreset` | Each count ≥ 0 AND at least one count > 0 once a scan has run. |
| Scan progress (`#sc-prog-bar` / `-label` / `-pct`) | computed | Width 0–100%, label includes `%`. |
| **Scan results table** | `G.results` from bulk Tradier quotes + enrichment | At least one row; each row has ticker (1-5 cap letters), price > 0, score 0–250, signal in `{GO, NO-GO}`. |
| Per-row RSI | `r.ind.rsi` (live via `calcRSIatIndex` after PR #22/#23 backfill) | **Critical**: not all rows = 50; at least 20% of top-60 rows diverge from 50. |
| Per-row ADX | `r.ind.adx` (live via `calcADX`) | **Critical**: not all rows = 30; spread > 5 across top-60. |
| Per-row MACD chip (in detail pane) | `r.ind.macd` (live via `calcMACD`) | **Critical**: not all rows = 0; sign mix present across top-60. |
| Per-row Sector PF rule | `SECTOR_PF[SECTOR_PF_MAP[su.s]]` | **Critical**: at least 60% of rows resolve PF > 0 (post-PR #21 sector-name fix). |
| Per-row Theme tag | `G_THEME_OVERLAY` / `IND.tickerAllThemes` | Either a theme name OR `—` (never blank). |
| Per-row GEX flow badge | `G.gexData` (cron) | If `G.gexData` populated, top-60 GO rows have a flow value or `RUN` pill. |

## Tab: Buy Sig (`bs`)

| Element | Source | Acceptance |
|---|---|---|
| GO count / NO-GO count / Avg score (`#bs-go` / `#bs-nogo` / `#bs-avg`) | computed from `G.results` | All integers; `go + nogo == G.results.length`; avg in 0–250. |
| Top sector chip (`#bs-sect`) | computed from `G.results` | Non-empty string; appears in `SECTOR_PF` known keys. |
| `#bs-pf` (sector GO/total) | computed | Format `N/M`, M > 0. |
| Total scanned (`#bs-scan`) | `G.results.length` | Matches `G.results.length`. |
| Per-card score pill | `r.score` from `scoreIt` | Integer 0–250; color class `go` ↔ `r.isGo`. |
| Per-card RSI/ADX line | `r.ind.rsi` / `r.ind.adx` | Same as scan-table check; not the 50/30 placeholders. |
| Per-card sub-line: T## / F## / RS / θ## | computed | T in 0–120; F in 0–60; RS includes sign and `%`; θ in 0–100 or `—`. |

## Tab: Ticker detail pane (opened from BS / SC)

| Element | Source | Acceptance |
|---|---|---|
| Header: ticker + price + GO/NO-GO badge | `r` from `G.results` | Matches the row that opened the pane. |
| IV/HV ratio chip | computed (Tradier `smv_vol` ÷ HV20 from `G_HIST_CACHE`) | Finite, > 0.2, < 5.0. Surfaced only when both inputs present. |
| **TECHNICAL INDICATORS grid — `RSI(14)`** | `ind.rsi` (live) | `ind.rsi !== 50` after history loads. |
| **TECHNICAL INDICATORS grid — `MACD Hist`** | `ind.macd` (live) | `ind.macd !== 0` after history loads. |
| **TECHNICAL INDICATORS grid — `ADX`** | `ind.adx` (live) | `ind.adx !== 30` after history loads. |
| `EMA20/50` cell | `ind.ema20`, `ind.ema50` (live via `calcEMA`) | `ind.ema20 !== price*0.99` && `ind.ema50 !== price*0.97` after history loads. |
| `EMA200` cell | `ind.ema200` (live via `calcEMA(200)`) | `ind.ema200 !== price*0.93` after history loads (requires ≥ 201 bars). |
| `ATR` cell | `ind.atr` (live via Wilder `calcATR(14)`) | `ind.atr !== price*0.015` after history loads. |
| `TF Aligned` cell | `ind.tf` (live via `calcTfAligned` — 8/21, 21/50, 50/200 EMA pairs) | Not all rows = 2; distribution across 0-3. |
| `Volume` cell | `ind.vol` from Tradier bulk quote | > 0; color reflects `vol > avgVol`. |
| `RS vs SPY 5d` cell | `ind.relStr5d` | Signed number; `0` is allowed but suspicious if every ticker shows `0`. |
| `52Wk High` cell | `ind.week52hi` from Tradier bulk quote | > 0, ≥ current price (within rounding). |
| `%-EMA Exit` cell | computed `ind.ema50 * 1.005` | Strictly derived from EMA50; fails alongside EMA50 if EMA50 is the placeholder. |
| OPTIONS CHECKLIST: Delta / Extrinsic / Spread / DTE / Strike / Expiry / Opt Price / OI/Vol | Tradier `/v1/markets/options/chains` (or `simOpt` placeholder) | When live: all populated, delta 0–1, DTE > 0, strike > 0. When `simOpt` is the source the pane should flag "no live chain". |
| Rule scorecard rows (~26) | `r.rules` from `scoreIt` | Each row has name, pass boolean, val string; total pts ≤ rule cap. |

## Tab: Positions (`pos`)

| Element | Source | Acceptance |
|---|---|---|
| Open positions count (`#pos-count`) | `G.positions.length` | ≥ 0; matches table row count. |
| Total cash / Account value / BP / Account balance badges | Tradier `/v1/accounts/<id>/balances` | All `$N` strings, N parses to finite > 0. |
| Data-source label (`#pos-src`) | string from `fetchPositions` | Non-empty. |
| Pending orders count (`#pos-pending-count`) | Tradier `/v1/accounts/<id>/orders` | ≥ 0. |
| Hero mobile equity / day P&L | computed | Numeric; matches the same values in the desktop summary within 1¢. |
| Per-row columns (Opened, Equity, Day P&L, Total P&L, Ticker, Exp, Strike, Stock Px, B/E, Qty, Delta, Mid, P&L%, DTE, Entry Px, ½/1/2 ATR, Trail status) | computed + Tradier | None of the dynamic columns show `—` after a fresh fetch (except for stock positions where exp/strike/delta legitimately empty). |
| Trail status badge | `G.tsState[sym].status` | One of `INACTIVE/WATCHING/ARMED/TRIGGERED/OFF/DISABLED`. |

## Tab: Portfolio (`pf`)

| Element | Source | Acceptance |
|---|---|---|
| Account display / cash display | Tradier balances | Both populated; cash matches positions tab. |
| Last-update timestamp (`#pf-last-update`) | `Date.now()` after refresh | < 30 min ago. |
| Summary stat-boxes: PROFIT FACTOR (`#cl-pf`) | computed from realized P&L | Finite, > 0 (or `∞`/`--` only when zero losses/zero positions). |
| Sector GOs (`#bs-pf` — shared with BS tab) | see BS tab. |
| Total value / Position count / Column count / Dead count / Top sector | computed from columns × rows | All finite ≥ 0; top sector is a known sector. |
| Doughnut charts (`#pf-chart-master`, `#pf-chart-sector`) | Chart.js | Canvas present, `getContext('2d')` succeeds, at least one slice. |
| Per-row Mid / Value / Dead badge | Tradier quotes | When ticker + exp + strike set: mid > 0, value > 0; Dead only when bid=ask=0. |

## Tab: Order Ticket (`order`)

| Element | Source | Acceptance |
|---|---|---|
| Symbol price (`#ord-sym-px`) | Tradier `/v1/markets/quotes` | $N matches header SPY/etc. for indices; for tickers, > 0. |
| Bid / Mid / Ask / Last / Mark / IV / sizes / spread / chg | Tradier quote (greeks on options) | All numeric; spread = ask − bid; mid = (bid+ask)/2. |
| Auto-select chip row (#asr-strike/exp/dte/gex/vol/oi/delta/score) | computed `autoSelectContract` | When triggered: all chips populated; delta 0–1; DTE > 0. |
| BP badge (`#ord-bp-badge`) | Tradier balances | `BP: $N`, N > 0. |
| P&L payoff cells (`#ord-be`, `-maxloss`, `-tgt10`, `-tgt20`, `-curpnl`) | computed | All `$N` once contract resolved. |
| Step-fill progress (`#sp-label`) | step-fill loop | `N / M` format when running. |
| Order result (`#ord-result`) | Tradier orders response | Text contains `filled` / `pending` / `error` after submit. |

## Tab: GEX / Flow (`gex`)

| Element | Source | Acceptance |
|---|---|---|
| Updated chip (`#gex-ts`) | `_fmtCT_NowTime()` + `G._gexLastFetchTs` | Includes `Updated:`; timestamp < 24h old. |
| Source label | `G._gexSource` | One of `local`/`github-cron`/`sim`. **Critical** if `sim` and we expected `cron`/`local`. |
| Bullish count / Prime count | computed | Integer ≥ 0. |
| Per-row Symbol / Spot / Net GEX / Call OI / Put OI / Flip / Call % / Put % / DTE / Exp / Strike / Flow / badges | `G.gexData[]` | Spot > 0; OIs integers ≥ 0; Call % + Put % ≈ 100; Flow in `{CALL HEAVY, PUT HEAVY, BALANCED}`. |
| SIM badge | `r.sim === true` | Only present when source is `sim`. |
| Progress phase / pct / ETA / detail | `runGex` state | Only present during fetch. |

## Tab: Industry (`ind`)

| Element | Source | Acceptance |
|---|---|---|
| As-of timestamp (`#ind-asof`) | `theme_scores.json:generated_at` | Within 24h for daily / weekly tf. |
| Timeframe tabs (`#ind-tf-*`) | UI state | Exactly one has class `active`. |
| Benchmark ticker (`#ind-bench`) | `theme_scores.json:benchmark` | Matches a known ETF symbol. |
| Rank-count pill (`#ind-rank-count`) | `ranked.length` | Format `N ranked`, N > 0. |
| Theme table body (`#ind-body`) | `theme_scores.json:themes` | ≥ 10 rows; each row has rank, name, score 0–100, RS columns, breadth %, trend arrow, member count > 0. |
| Triple-aligned panel (`#ind-aligned`) | computed intersection | Non-empty when at least 3 themes share top-decile across 3 TFs. |
| Heatmap (`#ind-heatmap`) | top-24 themes | 24 tiles; each has score 0–100. |
| Diagnostics rows (`#ind-diag`) | computed | All 5 rows present with numeric values. |

## Tab: News (`news`)

| Element | Source | Acceptance |
|---|---|---|
| Filter buttons (MARKET / WATCHLIST / POSITIONS / SCAN GOs / TICKER) | UI state | Exactly one has class `active`. |
| News-list (`#news-list`) | FMP `/api/v3/stock_news` (or Marketaux fallback) | When FMP key present: ≥ 3 cards; each card has symbol or `MKT`, source, title, time. |
| Per-card publish-time chip | `_ago(date)` | Includes `ago` / `min` / `hour`. |
| Status line (`#news-status`) | computed | Includes `articles`; if 0 → predicate warns. |

## Tab: Alerts (`al`)

| Element | Source | Acceptance |
|---|---|---|
| Alerts list (`#alerts-list`) | `G.alerts[]` | Either ≥ 1 alert OR explicit empty state; never an undefined render. |
| Per-alert dot color | `a.type` | Class in `{hc, go, warn, sys}`. |
| Per-alert timestamp | `a.ts` | Matches `HH:MM:SS`. |

## Tab: Watchlist (`wl`)

| Element | Source | Acceptance |
|---|---|---|
| Watchlist table | `localStorage:rrjcar_wl` → `G.wlTickers` | Array of uppercase tickers; render matches state. |
| Per-ticker quote panel | Tradier `/v1/markets/quotes` | Last/bid/ask all populated. |
| Chart canvas (`#wl-chart-canvas`) | ECharts + Tradier history | Chart instantiated, `getOption()` returns a config. |

## Tab: API (`api`)

| Element | Source | Acceptance |
|---|---|---|
| FMP / Tradier key inputs | localStorage | Length > 0 when stored. |
| Mode toggle | `localStorage:rrjcar_mode` | One of `sandbox`/`live`. |
| Account input | `localStorage:rrjcar_acct` / `_acct_live` | Matches `/^[A-Z]{2}\d{8}$/`. |
| Proxy URL | `localStorage:rrjcar_tradier_proxy` | Starts with `https://`. |
| Live-token | `localStorage:rrjcar_tradier_proxy_live_token` | Length ≥ 32, alnum. |
| API counter badges (`#api-counter-badge`, `#api-counter-tab`) | computed call count | < 300/min cap. |
| FMP / Tradier status pills (`#fmp-status`, `#tr-status`) | last test result | After `Test`: shows `OK` or `ERR <code>`. |
| Sync status (`#sync-status`) | Cloudflare worker KV | Includes `Success` or `Error`. |

## Cross-cutting checks

| Check | Acceptance |
|---|---|
| `G.results` not empty | After scan complete, `length > 0`. |
| `G_HIST_CACHE` populated for top 60 | After enrichment, top 60 tickers have ≥ 100 bars. |
| `G_FMP_CACHE` populated for top 60 | When FMP key configured, top 60 have analyst record. |
| `G.gexData` not all-`sim` | When Tradier configured and GEX cron ran, fewer than 10% of rows have `sim: true`. |
| `localStorage:op_cache_scan_results` size | < 5 MB; quota-failure path writes a console warn. |
| Worker rate state | `window._fmpRateLimited === 0`; `window._isFmpCircuitOpen() === false`. |

---

## Placeholder backfills — status

All known bulk-scan placeholders (`index.html:~18640`) now have backfills in `scoreIt` that resolve via history (in-memory `G_HIST_CACHE` → 24h `loadHistCache` localStorage). When a ticker has enough bars, the live computation overwrites the placeholder in place:

| Field | Placeholder (bulk pass) | Live calc | Min bars | PR |
|---|---|---|---|---|
| `ind.rsi` | `50` | `calcRSIatIndex(days,14)` | 16 | #22 / #23 |
| `ind.macd` | `0` | `calcMACD(days,12,26,9)` | 35 | #21 |
| `ind.adx`, `diPlus`, `diMinus` | `30` / undef / undef | `calcADX(days,14)` | 30 | #21 |
| Sector PF | `undefined` (key mismatch) | `SECTOR_PF[SECTOR_PF_MAP[su.s]]` | n/a | #21 |
| `ind.ema20` | `price * 0.99` | `calcEMA(days,20)` | 21 | this PR |
| `ind.ema50` | `price * 0.97` | `calcEMA(days,50)` | 51 | this PR |
| `ind.ema200` | `price * 0.93` | `calcEMA(days,200)` | 201 | this PR |
| `ind.atr` | `price * 0.015` | Wilder `calcATR(days,14)` | 15 | this PR |
| `ind.tf` | `2` | `calcTfAligned(days)` — agreement count across 8/21, 21/50, 50/200 EMA pairs | 200 | this PR |
