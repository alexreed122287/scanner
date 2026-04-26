# MAP.md — Where to look when something breaks

This is an index for the scanner codebase. The whole runtime app lives in
[`index.html`](index.html) (~18,400 lines, two `<script>` blocks). When a
feature breaks, find it in the **subsystem table** below, jump to the line
range, and read down. When you know the function name but not where it
lives, use the **function index** at the bottom.

This file is hand-maintained. If you add a new top-level function or
section, update both tables — `tools/audit/extract-sections.js` doesn't
regenerate this file because some hand-written context (the "if X breaks,
look here" pointers, the section descriptions) has no autogen source.

---

## Architecture in one paragraph

The scanner is a single-page vanilla-JS app served as a static
`index.html`. All Tradier API calls go through a Cloudflare Worker proxy
(`worker/tradier-proxy/`) that injects the API key server-side. A nightly
GH Actions cron (`industry/score_themes.py`) generates
`industry/theme_scores.json` for sector relative-strength data. There is
no build step — `index.html` is the source of truth and what GH Pages
serves.

Global state lives on a single object `G` (declared around line 3845).
Persistent state lives in `localStorage` under `rrjcar_*` keys. A
session-only trade token lives at `window._tradeToken` (never persisted).

---

## Subsystem map

Lookup pattern: find the symptom in the **owns** column, jump to the line
range, read top-to-bottom. The first script block runs lines 2425-10537;
the second runs 10539-18404.

| Subsystem | Lines | Owns |
|---|---|---|
| **Boot & API Counter** | 2427-2626 | Fetch monkey-patch, request counter, X-Live-Token + X-Trade-Token header injection |
| **Tradier auth** | 2628-2648 | `_getTradierKey`, proxy-aware key lookup |
| **Trade token** | 2650-2748 | `promptTradeToken`, modal, badge, `_ensureTradeToken` |
| **FMP queue / cache** | 3070-3860 | FMP rate-limited request queue, per-ticker FMP cache helpers |
| **Global state `G`** | 3845-3870 | `G = { results, filtered, gexData, ... }` declaration |
| **Utils** | 3869-3897 | `eid`, `_esc`, `fmt2`, `fmtP`, `fmtD`, `fmtK`, `clamp`, `toast` |
| **Sector multi-select** | 3898-4047 | Multi-sector filter dropdown, sector counts, label |
| **Sector exclusion** | 4049-4115 | Hard-filter entire sectors from scan results |
| **Mobile filter bar** | 4118-4150 | `toggleMobileFilters` collapse/expand |
| **Tab switcher** | 4155-4243 | `switchTab`, deep-link preservation |
| **ASR (auto-select)** | 4274-4502 | Auto-pick best contract by GEX score, expiration calendar |
| **Quote panel** | 4562-4776 | Live quote fetch, AH detection, render |
| **Step-fill engine** | 4783-4937 | Limit-at-each-step fill, slow market-fill fallback |
| **Order ticket** | 5074-5487 | `previewOrder`, `submitOrder`, OCC symbol builder, qty calc |
| **Order ticket UI** | 5489-6041 | Stock vs option mode, trailing stop UI wiring |
| **Equity trailing stop** | 5601-5847 | Poll Tradier price, trail stop server-side |
| **Smart Exits config** | 6043-6164 | ATR / EMA / HV math, config persist |
| **Smart Exits engine** | 6377-6505 | Poller, status render, intraday emergency + EOD logic |
| **Order block detector** | 6522-6892 | LuxAlgo SMC bearish OB + institutional OB, distance math |
| **Indicator math** | 6896-6947 | RSI, RSI accel, MFI, CMO |
| **FMP cache** | 6948-7019 | per-ticker FMP analyst data cache |
| **Performance analytics** | 7050-7261 | Kelly, per-rule win rate, IV/HV buckets, render |
| **Closed-trade enrichment** | 7278-7325 | `_captureEntrySnapshot` writes to `G.posOpenData` |
| **Theme overlay (daily)** | 7367-7444 | Loads `theme_scores.json`, applies to scoring |
| **Theme overlay (intraday)** | 7467-7625 | `_ensureIntradayThemeRS`, top-themes leaderboard strip |
| **Earnings calendar** | 7629-7733 | FMP bulk fetch, per-ticker DTE lookup |
| **Result rank comparator** | 7735-7787 | Multi-key tiebreaker for `G.results.sort()` |
| **`scoreIt` scoring** | 7790-7995 | The 19-rule scoring function — single source of truth for "GO"/"NO-GO" |
| **TradingView embed** | 7996-8011 | (declined; render is no-op) |
| **Detail pane** | 8013-8420 | Per-ticker detail render, options chain table |
| **Push notifications** | 8480-8520 | Browser Notifications API |
| **Quick-buy / watchlist add** | 8521-8576 | Single-click market BUY for shares |
| **Theme toggle** | 8579-8642 | Light/dark mode |
| **renderBuySig** | 8640-8772 | Renders the BUY SIGNALS list (sticky tab) |
| **Custom tickers** | 8773-8819 | User-defined ticker overlay |
| **Scan progress** | 8820-8853 | Header pill + progress bar |
| **Auto-scan engine** | 8854-8965 | 15-min auto-rescan timer |
| **Scan dispatcher** | 8966-9356 | `setScanComplete`, FMP queue dispatch, indicator queue dispatch |
| **`finishScan`** | 9359-9742 | Final filter / sort / render after enrichment drains |
| **Filters** | 9743-9905 | `getIndFilter`, `applyFilters`, indicator-pass filtering |
| **Scan settings** | 9907-9990 | `saveScanSettings` / `loadScanSettings` / `resetScanSettings` (rrjcar_scan_settings_v2) |
| **OB filter** | 9991-10034 | Toggle OB-clear + instrument-OB filters |
| **Export GO** | 10035-10166 | Copy GO tickers as CSV |
| **Sentiment panel** | 10168-10353 | Adanos F&G iframe, regime badge, sparkline |
| **`renderScan`** | 10377-10538 | Renders the FULL SCANNER table |
| **GEX cache** | 10540-10588 | `loadGexCache`, `saveGexCache`, freshness check |
| **GEX auto-schedule** | 10590-10670 | Fire `runGex` at 9:35 / 12:00 / 15:00 ET |
| **`runGex`** | 10671-10918 | Pulls option chains, computes GEX magnitude, gamma flip strike |
| **Watchlist** | 10920-11050 | Add / remove / render WL tickers; copy / clear |
| **Watchlist chart panel** | 11053-11239 | Candle chart + EMA 10/20/50 + S/R for selected WL ticker |
| **Position parsing** | 11240-11250 | `parseOccSymbol` — OCC option symbol → underlying / strike / exp |
| **Positions tab** | 11252-11772 | Fetch positions from Tradier, render table, P&L per row |
| **Cumulative P&L stats** | 11774-11848 | Header stats: total P&L, day P&L, count |
| **Trailing stop engine** | 11850-12112 | Per-position trailing stop, poll, execute close |
| **P&L chart** | 12114-12451 | Position P&L payoff curve, breakeven, hover tooltip |
| **Position close** | 12453-12602 | `clearPositions`, `buyOrder`, `closePosition` |
| **Balances** | 12604-12646 | Fetch balances + cash from Tradier |
| **Roll engine** | 12648-13341 | Modal for rolling option to a new strike/expiry |
| **Midnight refresh** | 13347-13363 | Cron-style daily reset |
| **Closed trade matcher** | 13364-13772 | Match buy/sell pairs from Tradier order history → closed trades |
| **Closed-trade chart** | 13778-13828 | Per-trade P&L curve at close |
| **Notifications config** | 13830-13947 | Cooldown persistence, EmailJS settings, browser permission |
| **High-conviction alerts** | 13948-14199 | Browser notif + email + auto-fill modal flow |
| **Auto-trader** | 14200-14623 | (Disabled per user) auto-execute on high-conviction signals |
| **Strategy modes** | 14624-14679 | High-conviction / Breakout / Momentum / Best ITM presets |
| **API tab** | 14680-15104 | Save/test/clear keys, FMP cache clear, live-mode token UI |
| **Header clock + quotes** | 15105-15208 | SPY/QQQ live ticker in header |
| **App settings** | 15210-15321 | App-level settings persistence |
| **Version banner** | 15323-15349 | One-time post-deploy "UPDATED" banner |
| **Contract panel** | 15351-15596 | All-calls-through-365d table for a single ticker, sorted by GEX score |
| **Contract watchlist** | 15598-15831 | Per-contract watchlist (separate from ticker WL) |
| **Tradier fetch wrapper** | 15833-15976 | `tradierFetch` with TTL cache + global rate limiter |
| **Bounded localStorage** | 15978-16071 | Per-ticker cache eviction, stale banner |
| **Portfolio builder** | 16073-17807 | Multi-column portfolio (paste/CSV/Tradier auto-pull), charts, recompute |
| **`init`** | 17811-17978 | Bootstrap on DOMContentLoaded — wires every UI element, restores state |
| **Industry strength tab** | 17980-18404 | Renders `theme_scores.json` as a sortable theme leaderboard |

---

## "If X breaks, look here"

Symptom-driven cheat sheet. Use this when you see a bug but don't know
the function name. Each entry points to the line range and the function
that owns the rendering / behavior.

| Symptom | Look at |
|---|---|
| "GO/NO-GO classification is wrong" | `scoreIt` (line 7790). Rule order, weights, and tiebreakers are all here. |
| "Sort order is weird, similar tickers in weird order" | `_resultRankCompare` (line 7735). Multi-key tiebreaker. |
| "Strong Sector lights up but daily theme says weak" | `_ensureIntradayThemeRS` (line 7467) + `getThemeStrengthLive` (line 7593). Combined daily + intraday RS. |
| "Theme leaderboard strip empty / wrong" | `renderTopThemesStrip` (line 7535). Filters by member count >=3. |
| "Earnings filter not catching X" | `getDaysToEarnings` (line 7707) + `G_EARNINGS_CACHE` at line 7584. |
| "Scan stalls at 199/200 forever" | Watchdog logic in indicator queue around line 9605. There's a comment from a prior fix. |
| "Auto-scan didn't fire" | `autoScanTick` (line 8896) — checks market hours + `isMarketHours`. |
| "GEX didn't auto-fire at 9:35" | `_gexScheduleTick` (line 10630) — F-1 fix to range debounce is here. |
| "GEX Call% number looks wrong" | `runGex` line ~10744 — `callPctOI * 0.6 + callPctVol * 0.4` blend. |
| "Position DTE shows --" | `renderPositionsTable` (line 11502). A-1 fix (regex `\d{2}` not `d{2}`) lives in the consolidated DIT/DTE block ~11505. |
| "Trailing stop didn't trigger" | `executeTsClose` (line 12049) + `startTsPoller` (line 11878). |
| "Smart Exit fired at wrong price" | `startSmartExitsPoller` (line 6377) → uses `computeATR` (6093), `computeEMA` (6147). |
| "Closed trade missing entry rules / IV / HV" | `_captureEntrySnapshot` (line 7278) writes; `matchTrades` (line 13372) reads. localStorage key: `rrjcar_pos_open`. |
| "Roll modal shows wrong chain" | `rollLoadChain` (line 12843) + `rollFetchBest` (line 13102). |
| "Portfolio cash not showing" | `pfAutoPullTradier` (line 16887). F-7 wraps positions in sentinel-catch so cash still renders if positions error. |
| "Portfolio paste lost a row" | `pfParseLine` (line 17404), `pfParseBlock` (line 17536), `pfNormalizeDate` (line 17631). |
| "Industry tab shows 'No data yet'" | `renderIndustryTab` (line 17992). Fetches `industry/theme_scores.json`. |
| "High-conviction modal won't dismiss" | `hcModalSubmit` / `hcModalCancel` / `hcModalSkip` (line 14096+). |
| "Alert spam on page reload" | `G_NOTIF_COOLDOWNS` at line 13831 — F-2 added localStorage persistence with 24h TTL. |
| "Email alert never sends" | `sendEmailJsAlert` (line 13993) — needs EmailJS keys configured in API tab. |
| "TRADE badge stuck on locked" | `promptTradeToken` (line 2689). Token lives at `window._tradeToken`, memory-only. |
| "Auth error: X-Live-Token" | Worker side: `worker/tradier-proxy/src/index.js:147`. Client side: `_getTradierKey` (line 2642), fetch monkey-patch line 2552. |
| "Sandbox vs live mode toggling weirdly" | `getTradierCreds` (line 4244) + URL `?mode=` query. Worker default is sandbox. |
| "API call counter at 0 despite scan running" | Fetch monkey-patch at line 2552 — only counts when `endpointLabel` returns truthy. |
| "Theme overlay shows zero / stale" | `_loadThemeOverlayFromStorage` (line 7367), `loadThemeOverlay` in `init`. Source: `industry/theme_scores.json`. |

---

## Persistence / state map

When state is wrong on reload, check both the in-memory `G` and the
localStorage key.

| In-memory | localStorage key | Owns |
|---|---|---|
| `G.results`, `G.filtered` | (none — recomputed) | Scan results |
| `G.gexData` | `rrjcar_gex_cache_v1` | Last GEX run |
| `G.gexAutoSchedule` | `rrjcar_gex_schedule_v1` | "off" / "open" / "3x" |
| `G.wlTickers` | `rrjcar_wl` | Watchlist tickers |
| `G.positions` | (none — pulled fresh) | Tradier positions |
| `G.posOpenData` | `rrjcar_pos_open` | Entry-snapshot for closed-trade enrichment |
| `G.tsConfig`, `G.tsState`, `G.tsTriggered` | `rrjcar_ts_config`, `rrjcar_ts_state` | Trailing-stop config + state |
| `G.alerts` | (in-memory only) | Recent alerts (max ~50) |
| `G.equityTrail` | `rrjcar_eq_trail` | Equity-side trailing stop |
| `G.selectedSectors` | `rrjcar_sel_sectors` | Sector multi-select |
| `G.detailOpt` | (in-memory only) | Currently-open detail pane |
| `G_EARNINGS_CACHE` | `rrjcar_earnings_v2` | Earnings calendar |
| `G_NOTIF_COOLDOWNS` | `rrjcar_notif_cooldowns_v1` | High-conviction alert cooldowns (F-2) |
| `G_THEME_OVERLAY` | `rrjcar_theme_overlay_v1` | Daily theme RS scores |
| (closed trades) | `rrjcar_closed_trades` | Performance analytics input |
| (FMP cache) | `rrjcar_fmp_<ticker>` | Per-ticker FMP analyst data |
| (scan settings) | `rrjcar_scan_settings_v2` | F-6 schema bump |
| (smart exits) | `rrjcar_smart_exits_v1` | Smart Exits config |
| (auto-scan) | `rrjcar_auto_scan` | Auto-scan settings |
| (notif settings) | `rrjcar_notif_settings_v1` | Browser/email notif prefs |
| (app settings) | `rrjcar_app_settings_v1` | App-level prefs |
| `window._tradeToken` | **NEVER PERSISTED** — memory only, re-prompted per session | Trade-token gate for orders |
| `window._liveTokenCache` | (cached from `rrjcar_tradier_proxy_live_token`) | Live mode token |

---

## Workflow recipes

**"Add a new scan rule"** — edit `scoreIt` (line 7790), add to the rules
array. Update `_resultRankCompare` (7735) only if the rule should
participate in the tiebreaker. If the rule should be filterable, add a
checkbox in the HTML, then add it to `SCAN_FILTER_CHECKBOXES` (line 9886)
and `getIndFilter` (line 9743).

**"Add a new tab"** — add the tab button in HTML, add the panel div, then
register the tab id in `switchTab` (line 4155). If the tab needs
data-loading on activation, add the loader call inside `switchTab`'s
switch.

**"Add a new persisted setting"** — pick a localStorage key with the
`rrjcar_*_v<n>` convention. Write a save / load pair near the existing
ones at the end of the relevant subsystem. Hook the load into `init`
(line 17811). If the schema can ever change, version the key.

**"Change something the cron writes to `theme_scores.json`"** — edit
`industry/score_themes.py`. Run `python3 -m pytest industry/test_theme_scores.py`
to confirm the smoke test still passes against the new shape, OR update
the test if the shape itself is intentionally changing. The cron will
run the test as a hard gate before commit.

**"Tighten the worker's path allowlist"** — edit
`worker/tradier-proxy/src/index.js` (`ALLOWED_PATH_PREFIXES`,
`ALLOWED_EXACT_PATHS`). Run `bash tools/audit/fuzz-tradier-proxy.sh`
locally before deploying. Then `cd worker/tradier-proxy && npx wrangler
deploy`. Re-run the fuzz to confirm the gate behaves as intended.

---

## Function index (alphabetical)

When you know the function name and want the line, search this table.
Generated from `index.html`; regenerate with:

```bash
python3 -c "
import re
lines = open('index.html').read().split('\n')
fns = []
in_script = False
for i, ln in enumerate(lines):
    if '<script>' in ln: in_script = True
    if '</script>' in ln: in_script = False
    if not in_script: continue
    m = re.match(r'^function\s+([A-Za-z_\$][\w\$]*)\s*\(', ln)
    if m: fns.append((m.group(1), i+1))
for name, ln in sorted(fns, key=lambda x: x[0].lower()):
    print(f'| \`{name}\` | {ln} |')
"
```

| Function | Line |
|---|---|
| `_apiTestAppend` | 14807 |
| `_apiTestReset` | 14814 |
| `_captureEntrySnapshot` | 7278 |
| `_computeIvHvBuckets` | 7120 |
| `_computeKelly` | 7061 |
| `_computePerRuleStats` | 7081 |
| `_drainTradierQueue` | 15890 |
| `_ensureIntradayThemeRS` | 7467 |
| `_esc` | 3875 |
| `_etMinuteOfDay` | 10615 |
| `_fmpMarkQuotaExhausted` | 3078 |
| `_fmpProcessQueue` | 3087 |
| `_fmtPct` | 7143 |
| `_fmtUsd` | 7144 |
| `_getTradierKey` | 2642 |
| `_gexFreshWithin` | 10565 |
| `_gexScheduleTick` | 10630 |
| `_loadClosedTradesForPerf` | 7050 |
| `_loadNotifCooldowns` | 13830 |
| `_loadThemeOverlayFromStorage` | 7367 |
| `_overheadFromObs` | 6806 |
| `_pushPermBtnUpdate` | 8493 |
| `_renderSmartExitStatus` | 6411 |
| `_resultRankCompare` | 7735 |
| `_retryNext` | (inner — see line 9505) |
| `_saveNotifCooldowns` | 13844 |
| `_saveThemeOverlayToStorage` | 7380 |
| `_sectDDOutsideClick` | 3990 |
| `_seConfigKey` | 6078 |
| `_supportFromObs` | 6826 |
| `_todayUtc` | 7629 |
| `_tradierGcCache` | 15871 |
| `_updateTradeTokenBadge` | 2666 |
| `_whyRankedBelow` | 7772 |
| `_wlCopyFallback` | 11013 |
| `_wlDrawCandles` | 11128 |
| `addAlert` | 4150 |
| `addToScanner` | 10355 |
| `addWL` | 10922 |
| `ahDelta` | 6698 |
| `applyAutoScanSettings` | 8879 |
| `applyCandidate` | 4496 |
| `applyDefaultsToAll` | 11405 |
| `applyDefaultTsConfig` | 11387 |
| `applyFilters` | 9745 |
| `applySmartExitsToUi` | 6446 |
| `applyStrategyMode` | 14624 |
| `applyTheme` | 8609 |
| `atCountAutoPositions` | 14281 |
| `atExecuteTrade` | 14513 |
| `atHasOpenPosition` | 14275 |
| `atLog` | 14245 |
| `atUpdateStats` | 14257 |
| `autoFillHighConviction` | 14029 |
| `autoScanCheckAlerts` | 8935 |
| `autoScanTick` | 8896 |
| `autoSelectContract` | 4336 |
| `autoSelectSimulated` | 4504 |
| `bsGC` | 15995 |
| `bsHardPrune` | 16025 |
| `bsSet` | 15985 |
| `buildDetail` | 8021 |
| `buildOccSym` | 5074 |
| `buyOrder` | 12474 |
| `cacheAge` | 16031 |
| `cacheGet` | 15849 |
| `cacheSet` | 15846 |
| `calcBreakeven` | 12147 |
| `calcCMO` | 6932 |
| `calcEffectiveStepSize` | 4815 |
| `calcEx` | 14687 |
| `calcMFI` | 6917 |
| `calcPnlAtPrice` | 12114 |
| `calcQtyFromBudget` | 5086 |
| `calcRSIAccel` | 6908 |
| `calcRSIatIndex` | 6896 |
| `cancelOrder` | 4904 |
| `cancelRollFill` | 13146 |
| `cancelStepFill` | 4852 |
| `chainRowClick` | 8403 |
| `chainSort` | 8390 |
| `checkHighConvictionSignals` | 14135 |
| `clamp` | 3886 |
| `clearBudget` | 5107 |
| `clearCustomTickers` | 8780 |
| `clearFilters` | 9965 |
| `clearFmpCache` | 14781 |
| `clearKeys` | 14793 |
| `clearOrder` | 5472 |
| `clearPositions` | 12461 |
| `closeDetailPane` | 8013 |
| `closeRollModal` | 12690 |
| `closeSectorDropdown` | 4004 |
| `closePosition` | 12532 |
| `computeATR` | 6093 |
| `computeEMA` | 6147 |
| `computeHV` | 6123 |
| `computeTrailInitialStop` | 5579 |
| `copyExportModalText` | 10121 |
| `cpBuyNow` | 15580 |
| `cpSortBy` | 15568 |
| `cwClearExpired` | 15719 |
| `cwGetAll` | 15602 |
| `cwRemove` | 15711 |
| `cwRenderTable` | 15643 |
| `cwSaveAll` | 15606 |
| `cwToggleWatch` | 15610 |
| `decorateIndustry` | 18300 |
| `decorateSentiment` | 10271 |
| `detectInstitutionalOBs` | 6695 |
| `detectOrderBlocks` | 6567 |
| `doBuyCall` | 12488 |
| `doBuyPut` | 12489 |
| `doClose` | 12490 |
| `doRoll` | 12648 |
| `drawPnlChart` | 12157 |
| `eid` | 3869 |
| `excludedFilteredResults` | 4086 |
| `executeTsClose` | 12049 |
| `exportGoTickers` | 10035 |
| `fetchBalances` | 12604 |
| `fetchClosedPositions` | 13450 |
| `fetchLiveQuote` | 4586 |
| `fetchOptionContract` | 5893 |
| `fetchOptionQuote` | 4640 |
| `fetchPositions` | 11252 |
| `fetchPositionsDirect` | 11284 |
| `fetchStockQuote` | 4618 |
| `fgSparklineSVG` | 10199 |
| `filterSectorOptions` | 4040 |
| `finishScan` | 9359 |
| `fireBrowserNotif` | 13948 |
| `fireEmailAlert` | 13965 |
| `fmt2` | 3881 |
| `fmtD` | 3883 |
| `fmtK` | 3884 |
| `fmtP` | 3882 |
| `formatOpenedDateTime` | 11470 |
| `fmpCacheKey` | 6948 |
| `gatherKnownSectors` | 3898 |
| `generateLiveModeToken` | 15082 |
| `getAutoTraderSettings` | 14229 |
| `getCustomTickerList` | 8792 |
| `getDaysToEarnings` | 7707 |
| `getIndFilter` | 9743 |
| `getNotifSettings` | 13903 |
| `getThemeStrength` | 7445 |
| `getThemeStrengthLive` | 7593 |
| `getTradierCreds` | 4244 |
| `getTradierCredsQuick` | 5601 |
| `getTsConfig` | 11421 |
| `getTsDefaultSettings` | 11376 |
| `getTvSettings` | 7996 |
| `getVisibleSectors` | 3938 |
| `hcModalCancel` | 14114 |
| `hcModalSkip` | 14126 |
| `hcModalSubmit` | 14096 |
| `hideStaleBanner` | 16066 |
| `histCacheKey` | 6466 |
| `inWatchlist` | 8567 |
| `indCopyFallback` | 18034 |
| `indCopyMembers` | 18014 |
| `indDraw` | 18103 |
| `indDrawHist` | 18333 |
| `indEsc` | 17980 |
| `indFmt` | 17981 |
| `indFmtAsOf` | 18086 |
| `indRenderUnassigned` | 18042 |
| `indRsClass` | 17982 |
| `indScoreClass` | 17990 |
| `indSetTF` | 18075 |
| `init` | 17811 |
| `injectSentimentBadge` | 10253 |
| `intradayRsToScore` | 7526 |
| `isAHTrade` | 4684 |
| `isCloseAction` | 4778 |
| `isMarketHours` | 14268 |
| `loadAppSettings` | 15258 |
| `loadAutoScan` | 8854 |
| `loadAutoTraderSettings` | 14214 |
| `loadAutoTraderState` | 14379 |
| `loadBsHideNoGo` | 8599 |
| `loadCustomTickers` | 8785 |
| `loadEarningsCacheFromStorage` | 7631 |
| `loadFmpCache` | 6950 |
| `loadGexCache` | 10577 |
| `loadGexSchedule` | 10607 |
| `loadHistCache` | 6468 |
| `loadKeys` | 14986 |
| `loadNotifSettings` | 13882 |
| `loadOBCache` | 6524 |
| `loadPortfolio` | 17807 |
| `loadScanSettings` | 9926 |
| `loadSentiment` | 10168 |
| `loadSmartExitsConfig` | 6079 |
| `loadWL` | 10920 |
| `makeMeter` | 13808 |
| `marketDaysBetween` | 4265 |
| `matchTrades` | 13372 |
| `minutesUntilMarketClose` | 6167 |
| `obCacheKey` | 6522 |
| `onBsSearch` | 8588 |
| `onOBFilterChange` | 9991 |
| `onOrderOtypeChange` | 5549 |
| `onOrderTypeChange` | 5492 |
| `onScSearch` | 8606 |
| `onSectorCheckboxChange` | 4023 |
| `onSymbolChange` | 4576 |
| `openContractPanel` | 15359 |
| `overheadInstOBDistance` | 6857 |
| `overheadOBDistance` | 6848 |
| `parseOccSymbol` | 11240 |
| `parseOccSymbolFull` | 13364 |
| `pfAddColumn` | 16477 |
| `pfAddRow` | 16417 |
| `pfAutoPullTradier` | 16887 |
| `pfBuilderAdd` | 17255 |
| `pfBuilderClear` | 17292 |
| `pfBuilderKindChange` | 17245 |
| `pfChartOpts` | 17105 |
| `pfClearColumn` | 16492 |
| `pfClosePasteModal` | 17388 |
| `pfColor` | 16096 |
| `pfCopyAllTickers` | 11034 |
| `pfDeleteColumn` | 16484 |
| `pfDeleteRow` | 16422 |
| `pfDownloadCSVTemplate` | 17319 |
| `pfEnrichUnknownSectors` | 16203 |
| `pfEsc` | 16339 |
| `pfExportCSV` | 17777 |
| `pfGenId` | 16164 |
| `pfGetCol` | 16165 |
| `pfGetRow` | 16166 |
| `pfImportPasted` | 17715 |
| `pfInferYear` | 17394 |
| `pfLoad` | 16110 |
| `pfLoadStrikesFor` | 16590 |
| `pfNormalizeDate` | 17631 |
| `pfOccSymbol` | 16169 |
| `pfOpenPasteModal` | 17226 |
| `pfParseBlock` | 17536 |
| `pfParseLine` | 17404 |
| `pfParseMultiSharesLine` | 17499 |
| `pfParsePreview` | 17657 |
| `pfPopulateExpiries` | 16565 |
| `pfPopulateStrikes` | 16668 |
| `pfRecomputeStats` | 17072 |
| `pfRefreshAll` | 16796 |
| `pfRefreshRow` | 16749 |
| `pfRenameColumn` | 16472 |
| `pfRenderColumn` | 16276 |
| `pfRenderColumnCharts` | 17189 |
| `pfRenderCharts` | 17137 |
| `pfRenderRow` | 16341 |
| `pfRenderStaged` | 17297 |
| `pfResetAll` | 16499 |
| `pfRowField` | 16427 |
| `pfSave` | 16161 |
| `pfSaveRow` | 16454 |
| `pfSectorFor` | 16181 |
| `pfTickerChanged` | 16509 |
| `pfUploadCSV` | 17338 |
| `pollOrderStatus` | 4893 |
| `populateAsrMonths` | 4306 |
| `populateSectorCheckboxes` | 3917 |
| `previewOrder` | 5115 |
| `promptTradeToken` | 2689 |
| `pushNotify` | 8480 |
| `quickBuyShares` | 8521 |
| `reclassifyGoThreshold` | 4095 |
| `refreshWL` | 10924 |
| `regimeColor` | 10219 |
| `removeWL` | 10923 |
| `renderAlerts` | 14680 |
| `renderBuySig` | 8640 |
| `renderClosedTable` | 13625 |
| `renderContractPanel` | 15482 |
| `renderGex` | 10896 |
| `renderIndustryTab` | 17992 |
| `renderPerformanceTab` | 7150 |
| `renderPortfolio` | 16221 |
| `renderPosChart` | 12423 |
| `renderPositionsTable` | 11502 |
| `renderQuotePanel` | 4708 |
| `renderScan` | 10377 |
| `renderSentimentTab` | 10324 |
| `renderTickerChart` | 8168 |
| `renderTopThemesStrip` | 7535 |
| `renderTsStatusRow` | 11890 |
| `renderTV` | 8006 |
| `requestNotifPermission` | 13929 |
| `requestPushPerm` | 8500 |
| `resetOneTsState` | 12036 |
| `resetOrderForm` | 12495 |
| `resetQuotePanel` | 4562 |
| `resetScanSettings` | 9945 |
| `resetTsState` | 12453 |
| `rnd` | 3885 |
| `rollFetchBest` | 13102 |
| `rollFetchLeg1Quote` | 12725 |
| `rollGetCreds` | 12705 |
| `rollLoadChain` | 12843 |
| `rollLoadExpirations` | 12804 |
| `rollLog` | 12695 |
| `rollRenderChainTable` | 13078 |
| `rollSelectBest` | 12958 |
| `rollSelectContract` | 12914 |
| `rollUpdateNet` | 13106 |
| `runGex` | 10671 |
| `saveAlertSettingsBtn` | 13849 |
| `saveAppSettings` | 15210 |
| `saveAutoScan` | 8866 |
| `saveAutoTraderSettings` | 14200 |
| `saveAutoTraderState` | 14368 |
| `saveCustomTickers` | 8773 |
| `saveEarningsCacheToStorage` | 7653 |
| `saveEquityTrail` | 3865 |
| `saveFmpCache` | 6961 |
| `saveGexCache` | 10550 |
| `saveGexSchedule` | 10610 |
| `saveHistCache` | 6478 |
| `saveKeys` | 14698 |
| `saveNotifSettings` | 13863 |
| `saveOBCache` | 6534 |
| `saveScanSettings` | 9907 |
| `saveSelectedSectors` | 3862 |
| `saveSmartExitsConfig` | 6088 |
| `saveTsConfig` | 11433 |
| `saveWL` | 10921 |
| `scheduleMidnightRefresh` | 13347 |
| `scoreGexForDate` | 4274 |
| `scoreIt` | 7790 |
| `searchCustomTicker` | 8803 |
| `sectorAllowed` | 4049 |
| `sectorCounts` | 3908 |
| `selectAllSectors` | 4009 |
| `sendEmailJsAlert` | 13993 |
| `setGexSchedule` | 10661 |
| `setLimitToAsk` | 4765 |
| `setLimitToBid` | 4749 |
| `setLimitToMid` | 4757 |
| `setScanComplete` | 8966 |
| `setScanProgress` | 8820 |
| `sfLog` | 4842 |
| `showAutoSubmitModal` | 14065 |
| `showExportModal` | 10085 |
| `showPosError` | 11374 |
| `showQuoteLoading` | 4570 |
| `showSimQuote` | 4664 |
| `showStaleBanner` | 16045 |
| `showVersionBanner` | 15323 |
| `simInd` | 5858 |
| `simOpt` | 5879 |
| `simQuote` | 5849 |
| `sleep` | 4937 |
| `sortTable` | 10142 |
| `starHTML` | 8579 |
| `startAutoScan` | 8890 |
| `startEquityTrailPoller` | 5610 |
| `startGexAutoSchedule` | 10652 |
| `startSmartExitsPoller` | 6377 |
| `startTsPoller` | 11878 |
| `stopAutoTrader` | 14352 |
| `stopEquityTrailPoller` | 5622 |
| `stopGexAutoSchedule` | 10658 |
| `stopSmartExitsPoller` | 6390 |
| `stopTsPoller` | 11886 |
| `submitLimitAtPrice` | 4861 |
| `submitOrder` | 5178 |
| `supportInstOBDistance` | 6861 |
| `supportOBDistance` | 6852 |
| `switchDetTab` | 8170 |
| `switchTab` | 4155 |
| `testEmailAlert` | 14009 |
| `tickerPassesSectorExclusion` | 4072 |
| `toast` | 3888 |
| `toggleAutoScanPanel` | 8911 |
| `toggleAutoTrader` | 14286 |
| `toggleBsHideNoGo` | 8592 |
| `toggleClosedChart` | 13778 |
| `toggleLightMode` | 8628 |
| `toggleMobileFilters` | 4119 |
| `togglePosChart` | 12408 |
| `toggleSectorDropdown` | 3974 |
| `toggleSmartExits` | 6396 |
| `toggleStepFill` | 4801 |
| `toggleTrailingStop` | 11860 |
| `toggleTsRow` | 11458 |
| `toggleWatchlistTicker` | 8568 |
| `tradierFetch` | 15940 |
| `tsLog` | 11850 |
| `updateAsrMonthLabel` | 4295 |
| `updateAutoScanPill` | 8916 |
| `updateClock` | 15105 |
| `updateClosedStats` | 13732 |
| `updateHeaderQuotes` | 15114 |
| `updateNotifPermStatus` | 13911 |
| `updateOrdChart` | 12362 |
| `updatePosStats` | 11779 |
| `updateRegimeBadge` | 10228 |
| `updateSectorLabel` | 3953 |
| `updateStepFillMode` | 4783 |
| `viewDetail` | 8421 |
| `wlClearAll` | 11018 |
| `wlCopyTickers` | 11004 |
| `wlRenderChart` | 11078 |
| `wlSelectTicker` | 11065 |
| `wlSetTimeframe` | 11057 |

---

## Adjacent files (not in `index.html`)

| Path | Owns |
|---|---|
| `worker/tradier-proxy/src/index.js` | Cloudflare Worker proxy: origin allowlist, path allowlist, X-Live-Token + X-Trade-Token gates, body cap, constant-time token compare |
| `worker/tradier-proxy/wrangler.toml` | Worker config: `ALLOWED_ORIGINS` |
| `industry/score_themes.py` | Nightly cron — fetches yfinance data, computes theme RS scores, writes `theme_scores.json` |
| `industry/build_master_list.py` | Builds `master_tickers.json` from `CURATED_THEMES` + `alex_tickers.csv` |
| `industry/audit_unassigned.py` | Auto-assigns themes to unassigned tickers via heuristic |
| `industry/test_theme_scores.py` | pytest smoke test — runs as a hard gate before cron commits new snapshot |
| `industry/master_tickers.json` | Generated — ticker → theme mappings |
| `industry/theme_scores.json` | Generated — daily theme RS scores (consumed by scanner's industry tab + theme overlay) |
| `alex_tickers.csv` | Curated ticker universe (~2,500 symbols) |
| `tools/audit/eslint.config.mjs` | ESLint config — security plugins only |
| `tools/audit/extract-scripts.js` | Pulls `<script>` blocks out of index.html for ESLint |
| `tools/audit/extract-sections.js` | Splits index.html along section dividers (audit aid only) |
| `tools/audit/fuzz-tradier-proxy.sh` | Read-only fuzz of the deployed worker |
| `.github/workflows/score_themes.yml` | Cron workflow with smoke-test gate + failure-issue notification |
| `.github/workflows/static-analysis.yml` | ESLint + Semgrep on every push/PR |
| `HANDOFF.md` | Session-handoff briefing for new Claude conversations |
