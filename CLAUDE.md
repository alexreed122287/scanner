# CLAUDE.md — Option Panda scanner context

This file is the handoff for new Claude Code sessions. Read it before doing anything else. It captures hard-earned context that's expensive to re-derive from the codebase.

## Repo layout

- `index.html` — single-page app, ~33k lines, all UI + all client JS. Edit here for almost everything.
- `HEALTHCHECK.md` — acceptance criteria for "every data element on screen is dynamic, not a placeholder, not stale". Source of truth for the runtime check registry.
- `worker/tradier-proxy/` — Cloudflare worker that proxies Tradier calls so the live token never ships to the browser.
- `industry/` — Python cron scoring scripts (`score_themes.py`, `audit_unassigned.py`). Outputs `theme_scores.json` / `theme_scores_history.json`.
- `gex/` — `gex_scores.json` cron output (3× daily via GitHub Actions). Drives the GEX/Flow tab + scan-table flow column.
- `.github/workflows/` — `parse-check.yml` (every push), `static-analysis.yml` (ESLint+Semgrep), `gex_scan.yml`, `score_themes.yml`, `daily_picks.yml`.

## Branch convention

All Claude development goes on `claude/<short-slug>` branches. Squash-merge to `main`. PRs may be opened non-draft and merged immediately — the user has standing approval for the create-PR-then-merge flow ("Continue without having to ask if I want to merge").

The auto-scan `claude/fix-macd-pf-adx-ExHF2` branch directive in the system prompt is stale; honor the user's explicit branch instructions instead.

## Running checks

The runtime check is the project's source of truth for "does the app work right now". Always use it after touching scoring, enrichment, or any data path:

```js
window.opHealthCheck();        // all registered checks, console.table, returns array
window.opHealthCheck('sc');    // filter by tab: hdr / sc / bs / pos / pf / order / gex / ind / news / al / wl / api / xref
window.opHealthCheckRender('hc-result');  // render into a DOM element
```

UI: API tab → DATA HEALTH CHECK card → ▶ RUN HEALTH CHECK.

Static parse-check (also runs in CI on every push to `index.html`):

```sh
node -e "
const fs=require('fs');
const html=fs.readFileSync('index.html','utf8');
const m=html.match(/<script\b[^>]*>([\s\S]*?)<\/script>/g)||[];
let errs=0;
for(const block of m){
  const body=block.replace(/^<script\b[^>]*>/,'').replace(/<\/script>\$/,'');
  if(!body.trim()) continue;
  try{ new Function(body); }
  catch(e){ errs++; console.log('PARSE ERR:', e.message.split('\n')[0]); }
}
console.log('parse errors='+errs);
"
```

## Architecture facts that matter

### Scoring pipeline

1. **Bulk scan** (~line 18640) iterates `UNIVERSE_FULL`, stamps every result with **placeholder** indicator values:
   - `ind.rsi = 50`, `ind.macd = 0`, `ind.adx = 30`, `ind.ema20 = price*0.99`, `ind.ema50 = price*0.97`, `ind.ema200 = price*0.93`, `ind.atr = price*0.015`, `ind.tf = 2`
   - These are intentional fallbacks so scoreIt produces a number when history is unavailable.
2. **`scoreIt(ticker, ind, opt)`** (~line 16070) **backfills** every placeholder above when history is available. Three-tier fallback for history resolution:
   - in-memory `G_HIST_CACHE[ticker]`
   - localStorage `loadHistCache(ticker)` (24h TTL, min 100 bars)
   - else null → leave placeholders, set `ind._synth = true`
3. **`simInd` / `simOpt` / `simQuote`** (lines 13345/13366/13339) — pure random fallbacks when no Tradier key. Mark `_synth: true`, `_synthSrc: 'simInd' | 'simOpt'`.
4. **Foreground enrichment** covers top-60 in ~30 sec. **Background enrichment** covers ranks 61-200 at ~30/min over ~7 min (`SC_ENRICH_LIMIT = 60`).
5. **Cache restore** on page load: `cacheGet(CACHE_KEYS.scanResults)` rehydrates `G.results`, then calls `scoreIt` on each row to re-backfill via `loadHistCache`. Without this, stale placeholders persisted before enrichment finished show on every reload.

### Indicator implementations (all in index.html)

| Function | Line | Notes |
|---|---|---|
| `calcRSIatIndex(days, period, idx)` | look near 14500 | Wilder RSI |
| `calcMACD(days, fast=12, slow=26, sig=9)` | look near 15300 | Returns histogram (signed) |
| `calcADX(days, period=14)` | line 15370 | Returns `{adx, diPlus, diMinus}` (Wilder) |
| `calcEMA(days, period)` | line 15383 (added PR #25) | k = 2/(p+1), SMA seed |
| `calcATR(days, period=14)` | line 15400 (added PR #25) | Wilder ATR |
| `calcTfAligned(days)` | line 15420 (added PR #25) | Counts agreement across 8/21, 21/50, 50/200 EMA pairs (0–3) |

### Sector PF lookup

`SECTOR_PF` keys are short (`Industrials`, `Energy`, …). `UNIVERSE_FULL` Tradier sector strings are long (`Producer manufacturing`, `Energy minerals`, …). Lookup goes through `SECTOR_PF_MAP[su.s] || su.s` (PR #21). If you add new sectors, update both.

### Auto-trader safety gates (PR #30)

`runAutoScanCycle` (~line 26060) and `submitOrder` (line 12360) both refuse to fire when:
- `r.ind._synth === true` (auto-trader only)
- `localStorage:rrjcar_tradier` and `rrjcar_tradier_proxy` are both unset (both)

The `_synth` flag propagates from simInd/simOpt and from scoreIt's history-missing path. As of PR #31, `simQuote` and the three static-universe row pushes also carry `r._synth` and `r._synthSrc='simQuote'` for direct row-level introspection. **Do not strip these gates** — they prevent real-money trades on randomly-generated indicators. Three static health checks (`api / Auto-trader synth-gate present in source`, `api / submitOrder sandbox refusal present in source`, `sc / simQuote stamps _synth on result row`) introspect the function source so a refactor accidentally removing a guard fails CI.

### `_synth` lifecycle (PR #32)

`scoreIt` no longer uses `if(!ind._synth)` — that guard never CLEARED the flag once set, so live-scan rows stayed flagged even after `_bgEnrichTick` populated `G_HIST_CACHE`. New rule: `if(ind._synthSrc !== 'simInd') ind._synth = !(_hist && _hist.length >= 30);`. The simInd path (no-key sandbox) stays flagged forever because the rest of the row is random; every other path reflects current history. `renderScan` adds `class='row-synth'` (opacity .55, lifted to .85 on hover/select) when `r.ind._synth || r._synth`, and adds a tiny `?` indicator in the SCORE column.

### Positions stale-quote race (PR #34)

`fetchPositionsDirect` snapshots `G.positions[*]` quote fields into `_prevQuoteByPos` keyed by OCC symbol BEFORE issuing the new bulk-quote fetch. Two merge points carry the previous values forward when the new fetch fails: a per-symbol miss inside the `.then`, and the outer `.catch` that fires when the whole quote fetch rejects. `p._quoteTs = Date.now()` is stamped only when a quote successfully populates `p.last`. `renderPositionsTable` derives two row classes from age:
- `pos-row-stale-quote` when `Date.now() - _quoteTs > 60_000` → amber tint + `STALE Xs` pill prepended to the TOTAL P/L cell.
- `pos-row-no-quote` when `_quoteTs` is missing AND `last == 0` (first fetch failed) → dimmed row + `NO QUOTE` pill.

Threshold matches the order-ticket's existing `FORCE_REFRESH_MS = 60s` constant. **Do not remove the `_prevQuoteByPos` merge** — without it the user sees P&L flash to \$0 on any quote-fetch hiccup.

### Tradier 429 cause attribution (PR #36)

`fetchDynamicUniverse` checks `resp.status === 429` after each Pass 1 / Pass 2 batch and stamps `window._tradierRateLimited = Date.now()`. The empty-screened fallback in `runScan` compares that timestamp to `Date.now()` and shows one of two toasts:
- Within 60s → `⚠ Tradier rate-limited (429) — retry in ~60s. Showing simulated data meanwhile.` + amber `RATE-LIMITED` universe label.
- Stale → existing `⚠ Screener failed — using static universe`.

Synthetic rows in either path carry `r._synthCause` (`'tradier-429'` vs `'screener-empty'`) for downstream attribution. Health check `sc / No recent Tradier 429 (PR #36)` fails inside 1 min, warns up to 5 min.

### bg-enrich honest accounting (PR #37)

The tick now bumps **exactly one** of three counters per iteration so the invariant `cursor === enriched + failed + skippedDone` holds. Badge text appends `· Nf` when `failed > 0`. **Do not add a fourth exit path without bumping a counter** — the `sc / bg-enrich accounting balances` health check will fail loudly if the totals diverge.

### Shadow-book fwd-return scheduler (PR #38)

`runShadowBookBackfill({ force })` wraps both `_shadowRefreshForward` (per-contract) and `_shadowRefreshScanForward` (per-ticker) with a 4h cooldown stored at `localStorage:rrjcar_shadow_backfill_ts`. `_shadowHasPending` short-circuits the API call when no entry is old enough (age ≥ 1d AND `fwd1d == null`). Scheduler fires 90s after `DOMContentLoaded` then every 4h. Silent unless something updates; emits a green `SYS` alert on success.

The console-callable signature `window.runShadowBookBackfill({ force: true })` bypasses the cooldown for manual triggering.

### localStorage quota signal (PR #39)

`cacheSet` no longer swallows `QuotaExceededError`. On a quota error it calls `bsHardPrune` (drops `rrjcar_ob_hist_`, `rrjcar_hist_`, `rrjcar_fmp_` caches) and retries once, then stamps `window._quotaErrors` (count, lastKey, lastTs). `#hdr-quota` header pill flips to `⚠ STORAGE FULL` at the first hit and stays visible until the user clicks it (which runs `_resetQuotaWarning`). The pill survives across navigations because `_renderQuotaBadge` runs from the same DOM-ready hook as `_updateSandboxBanner`.

`window._resetQuotaWarning()` is exposed for console use.

### Slim-cache layout

`localStorage:op_cache_scan_results` (key `CACHE_KEYS.scanResults`) holds top-200 results post-scan. Trimmed at write to avoid 5 MB Safari quota. Restored at page load and re-scored. **Do not increase SLIM_CAP without measuring serialized size.**

### Where the SANDBOX/SIM banner is wired

- Pill: `#hdr-sandbox` in header
- Toggle fn: `_updateSandboxBanner()`
- Fires on: `DOMContentLoaded`, `saveKeys()`

### Phase 2 continuous scoring (PR #57)

Four rules converted from binary to gradient scoring via `scalePts(val, lo, hi, maxPts)`:

| Rule | Before | After (Phase 2) |
|---|---|---|
| RSI 40-70 (max 8) | binary pass/fail | `max(0, 8 - (|rsi-55|/20)*8)` — peaks at RSI=55, zero outside ±20 |
| ADX > 25 (max 8) | binary pass/fail | `scalePts(adx, 22, 40, 8)` — floor 22, ceiling 40 |
| 52Wk Hi Prox <15% (max 10) | binary pass/fail | `scalePts(hiPct, 0, 1, 10)` — 0% = max, 15%+ = 0 |
| RS > SPY (max 8) | binary pass/fail | `scalePts(relStrVal, 0, 10, 8)` — uses `relStr21d` if available, else `relStr5d` |

**`pass` / `strong` semantics (applies to all rules):**
- `pass = pts > 0` (contributes to total score)
- `strong = pts >= max*0.5` for continuous rules; `strong = pass` for binary rules
- `passes[]` array and `_rulePassedByName()` filter on `strong`, not `pass` — preset MUST-PASS filters use `strong`

**Score clamp updated: 164 → 156.**

**`ind.relStr21d`** is computed in `scoreIt`'s history-backfill section: 21-day total return of ticker minus SPY over the same window, using `G_HIST_CACHE['SPY']`. Requires SPY history to be enriched (always true on live-scan path). Falls back to `relStr5d` (today's 1-day delta vs SPY) when SPY history is absent.

### Phase 2.5 threshold recalibration (PR #59/62)

Phase 2 continuous scoring shifted the observed distribution down ~15-16 pts at the median (measured 2026-05-19, live-API scan, 1,513 tickers). Thresholds updated by percentile-match:

| Constant | Old | New |
|---|---|---|
| `goThreshold` default in `scoreIt()` | 140 | **121** |
| `STRATEGY_MODES.highConviction.minScore` | 140 | **121** |
| `STRATEGY_MODES.breakout.minScore` | 125 | **115** |
| `STRATEGY_MODES.momentum.minScore` | 120 | **111** |
| `STRATEGY_MODES.bestItmCalls.minScore` | 145 | **138** |
| `STRATEGY_MODES.preMarket.minScore` | 140 | **121** |
| `sc-minscore` HTML input default | 130 | **116** |
| `loadAutoScan` threshold fallback | 110 | **98** |

The `sc-minscore` default appears in three places: the HTML `value=` attribute, `SCAN_SETTING_DEFAULTS['sc-minscore']`, and the `clearFilters()` reset. All three must stay in sync.

### GO gate — fundScore enforced (2026-06-12, audit M1.1)

Owner decision (Alex, 2026-06-12): the documented `fundScore ≥ 8` GO gate is now
ENFORCED in code. Previously `fundScore` was computed but ignored by `isGo`, so
chart-only tickers with zero analyst/sector confirmation could be flagged GO.

- Constant: `FUND_GO_GATE = 8` (declared above `scoreIt`)
- Both GO paths gate identically and must stay in sync:
  - `scoreIt`: `isGo = total >= goThreshold && !avoidBad && clamp(fundScore,0,30) >= FUND_GO_GATE`
  - `reclassifyGoThreshold`: `r.isGo = score >= thresh && !avoidBad && (r.fundScore||0) >= FUND_GO_GATE`
- fundScore sources (max 30): Analyst Revisions ↑ (+12), Analyst PT Exists (+8),
  Strong Sector theme bonus (±8). FMP down/keyless ⇒ GO count drops sharply —
  intended fail-closed behavior for a real-money signal.
- `reclassifyGoThreshold` empty-input fallback also reconciled 140 → 121 to
  match `scoreIt` (audit T4).

### GEX resilience (PR #56, #58)

**PR #56** (`_fetchOneChain` / `_fetchOneExpiry`): reads `r.text()` then `JSON.parse()` instead of `r.json()` directly; detects non-JSON responses (rate-limit plain text, "Restricted", HTML error pages) before attempting parse. Batch dispatch converted from `Promise.all` → `Promise.allSettled` so a single failed fetch doesn't abort the whole batch. `_gexFreshWithin` window widened from 30 min → **360 min (6 h)** so cron-hydrated data is treated as fresh for the full inter-cron interval.

**PR #58** (null-chain guard): When Tradier returns `{options: {option: null}}` for a ticker with no options, `_fetchOneChain` now returns `[]` instead of wrapping `null` into `[null]`. All three `forEach` loops in `_processChains` have `if(!opt) return` guards. Without these, a single null entry caused the forEach to throw on `.open_interest`, aborting the map before `G.gexData` was written — GEX tab rendered empty with no console error.

## What's live on `main` (recent PRs)

| PR | Subject | Why |
|---|---|---|
| #21 | MACD/ADX backfill + SECTOR_PF_MAP | RSI/MACD/ADX rules were reading bulk-scan placeholders → every row passed/failed identically |
| #22 | RSI backfill | Same class, RSI-specific |
| #23 | scoreIt history fallback to localStorage | Page reload showed RSI=50 because in-memory cache was empty at restore time |
| #24 | HEALTHCHECK.md + `opHealthCheck()` + API-tab UI panel | Built the runtime check that catches this class of regression |
| #25 | EMA/ATR/TF backfill + lazy-tab predicate fixes | Closed the remaining placeholder bookmarks |
| #26 | `ind._synth` flag + detail-pane SYNTHETIC badge | Surface synthetic state to user |
| #27 | `.github/workflows/parse-check.yml` | Catch syntax errors in CI |
| #28 | SANDBOX/SIM banner + simInd/simOpt `_synth` stamp | Global sandbox-mode signal |
| #29 | Sparse-coverage health-check fill (50 → 72 predicates) | Coverage for Order, Portfolio, News, Watchlist, Alerts, Pos, GEX, Ind |
| #30 | Auto-trader synth-gate + submitOrder sandbox refusal | Refuse real-money trades on `_synth: true` rows or with no credentials |
| #31 | simQuote stamps `_synth:true, _synthSrc:'simQuote'` + new health check | Detail pane was showing real-looking price next to flagged indicators on sandbox path |
| #32 | `.row-synth` dim on scan table + clear `_synth` after enrichment | Rank 61–200 placeholders were indistinguishable from real rows for ~7 min after a scan; scoreIt also wasn't clearing `_synth` once history landed, so the flag was stuck even on top-60 |
| #34 | Positions stale-quote race — carry forward prev quotes + visible flag | Quote-fetch failure in `fetchPositionsDirect` was rendering every row with last=0/pnl=0; now prev values merge from `_prevQuoteByPos` and rows over 60s old get a STALE pill + amber tint |
| #36 | Surface Tradier 429 cause in scan fallback | `Screener failed — using static universe` was indistinguishable between rate-limit and config issues; now `window._tradierRateLimited` is stamped and the toast/alert distinguishes |
| #37 | bg-enrich badge stops lying | Tick now bumps exactly one of `{enriched, failed, skippedDone}` per iteration; badge appends `· Nf` when failures > 0; tooltip shows full breakdown |
| #38 | Auto-schedule shadow-book fwd-return backfill | `_shadowRefresh*Forward` existed but had to be called manually; new `runShadowBookBackfill` runs 90s after load + every 4h with cooldown stamp |
| #39 | Surface localStorage quota failures in UI | `cacheSet` swallowed `QuotaExceededError` silently; new `#hdr-quota` pill + retry-after-prune logic + `_resetQuotaWarning` click handler |
| #45 | Weekend scoring fixes | `avoidBad` check was inverted (filtered good tickers); `ind.relStr21d` was never populated so RS rule always fell back to 5d; sort header default fixed |
| #47 | Wire `applyStrategyMode` to checkboxes + minScore | Strategy preset buttons weren't setting sc-minscore or toggling filter checkboxes |
| #48 | CLEAR button removes active preset highlight | Visual regression — selected preset stayed highlighted after clearing |
| #51 | FMP cache pre-warm + remove splash video | Pre-warms `G_FMP_CACHE` from localStorage before the score loop so first-scan fundamental data is available without waiting for async enrichment |
| #52 | GEX batched parallel dispatch | Replaced serial per-ticker fetches with batched parallel; significant speed improvement on GEX tab load |
| #53 | iPad/iOS crash fixes | Memory reductions for Safari OOM; removed apple-touch-startup-image splash links |
| #55 | Strip `_pool` from `r.opt` | 23× per-row size reduction in scan results; prevented localStorage quota exhaustion on large scans |
| #56 | GEX resilience + cron gating | `Promise.allSettled`, text-based non-JSON detection, `_gexFreshWithin(360)` — see architecture note above |
| #57 | Phase 2 continuous scoring port | RSI, ADX, 52Wk Hi, RS > SPY converted to gradient scoring; `pass`/`strong` decoupled; score clamp 164→156 |
| #58 | GEX null-chain fix | `_fetchOneChain` null guard + `_processChains` per-opt null guards; GEX tab was silently empty when any ticker had no options |
| #59 | Phase 2.5 threshold recalibration | goThreshold 140→121, all STRATEGY_MODES presets, sc-minscore 130→116, loadAutoScan 110→98 |
| #63 | Phase 3.1: TF Aligned tier port | TF Aligned binary 12 pts → tiered 4/8/12 pts for tf=1/2/3. Matches rrjcar line 3476. `pass = tfPts > 0`; `strong` uses binary-rule path (see bug 7.13). Deployed 2026-05-19; verified live — tf=3→12pts, tf=2→8pts, tf=1→4pts (CHRW), tf=0→0pts (AXS, RTX). |

## Known bug list (not yet shipped, ranked)

### Phase 3 deferred backlog

**7.8 — Audit-invariant violation for negative-pts rules**
28 of 200 rows violate `score === sum(pts where pass)`. GEX Call Flow emits `{pts:-6, pass:false}` as a penalty (24 rows); Broken Trend uses inline `score -= 5` with `{pts:0, pass:false}` (4 rows). Score values are correct (`sumAllPts === score` holds). The audit-invariant claim in §1.3 is slightly overstated — it holds for non-negative-max rules only. Resolution: emit penalty rules via Weak Sector pattern (`{pts:0, pass:true}` + separate `{n:'...Penalty', pts:-6, pass:true, isPenalty:true}`), or change audit to `sum(pts)` no-filter.

**7.9 — RS 5d/21d fallback strong-rate divergence**
Only 9 of 1,513 tickers in the May 19 scan got `relStr21d`; the other 1,504 used `relStr5d`. The 5d branch has passRate 60% but strongRate only 3.7% — almost no row earns a curve-strong score, so the RS rule is effectively invisible to preset MUST-PASS filters for 99.4% of the universe. Fix options: (a) widen SPY-history pre-fetch to ensure full-universe `relStr21d`; (b) reduce 5d branch max pts (currently 8, same as 21d — maybe 4-5).

**7.10 — ADX > 25 curve front-loading**
`ADX > 25` rule (max 8, scale 22→40) shows passRate 72% but strongRate only 8.5%. Most rows clear the floor (ADX 22-25) and earn 1-3 pts; very few reach 30-40 for ≥4 pts. Fix options: (a) tighten scale to 22→35; (b) accept as-is (ADX 22-25 is genuinely low-conviction).

**7.11 — Dead OR-branch in `_matchesPreset`**
`has('52Wk Hi Prox <5% (G-H)')` check always returns false — rule was renamed/removed. Safe to delete; no scoring impact. Phase 3 cleanup.

**7.12 — Stale `clamp(techScore, 0, 240)` ceiling**
Score clamp in `scoreIt` return still uses 240 (the old theoretical max). Practical max is ~156. No functional impact (observed max never approaches 240), but misleading. Phase 3 cleanup.

**7.13 — TF Aligned tier-rule `strong` field violates §1.2 invariant**
TF Aligned at tf=1 shows `strong: true` despite `pts (4) < max (12) * 0.5 = 6`. Current implementation uses binary-rule `strong = pass` path; continuous-rule semantics would give `strong = false`. Empirical impact: zero (only CHRW at score 61.9, far below any preset minScore). Resolution: extend `strong` computation to use `pts >= max * 0.5` for tiered rules (option 1 in wrap-up). 1-line edit. Phase 3.X cleanup.

## Phase 3.2 status (deferred)

Weight reduction on remaining floor rules (EMA20>EMA50 10→?, Price>EMA200 6→?, Sector PF 5→?) is deferred pending 24-48h observation of Phase 3.1 in production. Requires a fresh Method-B-style capture-then-rescore to isolate floor-rule contribution from market-tape noise. The afternoon distribution shift on 2026-05-19 (+10 median) was dominated by tape movement, not Phase 3.1's tier effect — same-ticker before/after comparison required to size Phase 3.2 correctly.

## Things to NOT do

- Don't strip `r.ind._synth` checks in auto-trader or submit paths. Two static health checks (PR #30) explicitly verify they remain in the function source.
- Don't relax the `loadHistCache` 100-bar minimum without checking that calcEMA(200) still functions on the result.
- Don't write to `op_cache_scan_results` without re-running through `JSON.stringify(...).length < 5*1024*1024` check.
- Don't merge a PR that touches `index.html` if the parse-check workflow goes red. The page won't load.
- Don't add fields to `r.ind` without considering whether `simInd` needs to populate them too.
- Don't change `SECTOR_PF` keys without updating `SECTOR_PF_MAP`.
- Don't modify the `avoidBad` check logic in `reclassifyGoThreshold` or preset-filter code — PR #45 fixed an inverted check (`rl.pass && rl.pts < 0`) that was blocking good tickers. The canonical avoidBad pattern uses the AVOID list directly, matching `scoreIt`.
- Don't change `sc-minscore` default in only one place — it appears in the HTML `value=` attribute, `SCAN_SETTING_DEFAULTS`, and `clearFilters()`. All three must stay in sync (currently all 116).
- Don't use `Promise.all` for GEX batch fetches — one rejected promise aborts the batch and spikes memory on Safari. Use `Promise.allSettled` (PR #56).

## Version bumping convention (added 2026-05-19)

Every PR that modifies code MUST bump the version before commit. Versioning
follows the date-count scheme:

    v{M}.{D}.{YY}.{N}

Where M/D/YY is the deploy date in Central Time (CT) and N is the count
of deploys today (starting at 0).

Before any commit that will be deployed, run this bump procedure:

1. Get today's date in CT: `date -d 'TZ="America/Chicago" now' +"%-m.%-d.%y"`
   (or equivalent for the platform). Result like "5.19.26".

2. Read current APP_VERSION from index.html.

3. If current version's M.D.YY matches today: increment N (e.g., v5.19.26.2
   becomes v5.19.26.3). If different (or current is legacy v2.18.x):
   set N = 0 (new day starts at v{today}.0).

4. Write the new version to BOTH places:
   - APP_VERSION constant (~line 27799)
   - `<meta name="op-build" content="...">` tag (line 14)

Both values must match exactly. They are the canonical "what's deployed"
source of truth.

Helper one-liner for shells with GNU date:

    TODAY=$(TZ="America/Chicago" date +"%-m.%-d.%y")
    CUR=$(grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' index.html | head -1)
    # parse N from CUR, increment if same day, else 0
    ...

Consumers of APP_VERSION pick up the change automatically:
- Header bar `#hdr-version` display
- Webhook payloads (lines 4488, 5847)
- Deploy-detector localStorage check (~line 27946) — triggers "new version"
  notification to users

The version bump itself triggers a user-facing "new version" notification
on every connected client when they next load Panda. This is a feature,
not a bug — it confirms the deploy reached them.

## Style notes

- The user prefers terse end-of-turn summaries (1-2 sentences).
- They have standing approval to push and squash-merge. Don't ask "should I merge?".
- They run the health check after every meaningful change and want fails/warns reported plainly.
- Severity tiers in the check registry: `critical` = trading decision, `important` = informs trading, `info` = cosmetic.
