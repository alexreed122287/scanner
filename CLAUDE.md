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

### Slim-cache layout

`localStorage:op_cache_scan_results` (key `CACHE_KEYS.scanResults`) holds top-200 results post-scan. Trimmed at write to avoid 5 MB Safari quota. Restored at page load and re-scored. **Do not increase SLIM_CAP without measuring serialized size.**

### Where the SANDBOX/SIM banner is wired

- Pill: `#hdr-sandbox` in header
- Toggle fn: `_updateSandboxBanner()`
- Fires on: `DOMContentLoaded`, `saveKeys()`

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

## Known bug list (not yet shipped, ranked)

1. **Tradier 429 cascade** — bulk-quote 429 retries fall through to simQuote silently. Now that simQuote stamps `_synth` (PR #31) the row will at least surface as synthetic; still worth a discrete log/toast distinguishing rate-limit failure from no-key sandbox.
2. **Background enrichment progress lying** — counter increments even when fetch fails. `bg-enrich-badge` shows `200/200` while `G_HIST_CACHE` has 80 entries.
3. **Forward-return tracking** — shadow-book mentions `fwd1d/fwd3d/fwd5d`; no current backfill job. Edge measurement is meaningless without it.
4. **localStorage quota write fail surfaces only in console** — user has no UI signal when slim-cache write fails.

## Things to NOT do

- Don't strip `r.ind._synth` checks in auto-trader or submit paths. Two static health checks (PR #30) explicitly verify they remain in the function source.
- Don't relax the `loadHistCache` 100-bar minimum without checking that calcEMA(200) still functions on the result.
- Don't write to `op_cache_scan_results` without re-running through `JSON.stringify(...).length < 5*1024*1024` check.
- Don't merge a PR that touches `index.html` if the parse-check workflow goes red. The page won't load.
- Don't add fields to `r.ind` without considering whether `simInd` needs to populate them too.
- Don't change `SECTOR_PF` keys without updating `SECTOR_PF_MAP`.

## Style notes

- The user prefers terse end-of-turn summaries (1-2 sentences).
- They have standing approval to push and squash-merge. Don't ask "should I merge?".
- They run the health check after every meaningful change and want fails/warns reported plainly.
- Severity tiers in the check registry: `critical` = trading decision, `important` = informs trading, `info` = cosmetic.
