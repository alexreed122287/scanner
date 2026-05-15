# Refactor Inventory — Panda ↔ RRJCAR parallels

Built during weekend scoring-engine work, 2026-05-15.
Purpose: track which Panda fixes have parallels in rrjcar, as input for a future shared-core extraction.

---

## Bug 1 — Broken Trend penalty sign flip

**Panda location:** `index.html:16796` — rule entry:
```js
res.push({n:'Broken Trend (penalty)', pass:!brokenTrend, val:brokenTrendVal, filter:false, pts:-5, isPenalty:true});
```
The actual score deduction at line 16795 is correct (`if (brokenTrend) { score -= 5; techScore -= 5; }`).
The sign flip lives in the *reclassify* path: `index.html:8711` (in `reclassifyGoThreshold`) and `index.html:18582` (in the preset GO filter):
```js
if(rl.pass && rl.pts && rl.pts < 0) avoidBad = true;
```
When trend is **intact** (good): `brokenTrend=false` → `pass=true`, `pts=-5`. This guard fires (`pass===true && pts<0`), setting `avoidBad=true` — which gates the ticker out of GO. The condition should check `!rl.pass` (penalty triggered = rule failed) rather than `rl.pass`.

**RRJCAR location:** No Broken Trend rule exists in rrjcar. Not applicable.

**Shareable?** No — Panda-specific rule, Panda-specific bug.

---

## Bug 2 — FMP cache pre-population

**Panda location:**
- `G_FMP_CACHE` declared: `index.html:15721`
- `loadFmpCache(ticker)` (reads localStorage, 24h TTL): `index.html:15725`
- `fetchFmpData(ticker)` (async, lazy-loads one ticker): `index.html:15745`; lazy-load check at lines 15746–15748
- `scoreIt` reads FMP synchronously: `index.html:16336` — `var fmp = G_FMP_CACHE[ticker] || loadFmpCache(ticker);`
- Scan loop entry: `runScan()` at `index.html:18966`; initial score loop at lines 19088–19136 (calls `scoreIt` inline per screened ticker)
- No bulk warm-up of `G_FMP_CACHE` from localStorage before the initial score loop; per-ticker lazy reads happen inside each `scoreIt` call during the scan

**RRJCAR location (reference implementation):**
- `loadFmpCache(ticker)`: `index.html:2329`
- `fetchFmpData(ticker)` lazy-load check: `index.html:2350–2353`
- `scoreIt` reads: `index.html:2417` — `var fmp = G_FMP_CACHE[ticker] || loadFmpCache(ticker);`
- Same lazy-load pattern; no bulk pre-pop in rrjcar either. The reference shows per-ticker lazy load as the accepted pattern.

**Shareable?** Partial — both use identical lazy-load. Saturday: determine whether a bulk warm-up pass before the score loop is actually needed (or whether the per-ticker localStorage reads in scoreIt are sufficient).

---

## Bug 3 — SPY in history cache

**Panda location:**
- `G_HIST_CACHE` declared: `index.html:14825`
- `fetchIndicatorHistory(ticker)` (Tradier, 400-day window): `index.html:14856`; Tradier call at line 14880
- SPY explicitly injected into scan universe inside `fetchDynamicUniverse`: `index.html:18751` — `if(!seen['SPY']) allTickers.push({t:'SPY', s:'ETF'});`
- Regime calc reads SPY history: `index.html:8665` — `var days = G_HIST_CACHE['SPY'] || null;`
- SPY result looked up in G.results at line 15966 (for intraday change reference)
- SPY is NOT in UNIVERSE_FULL by ticker (no static entry with `t:'SPY'`); it is added dynamically to the live screener batch only — meaning SPY history depends on the live scan path completing successfully and enrichment reaching SPY's rank.

**RRJCAR location:**
- Same dynamic injection pattern: `index.html:2676` — `if(!seen['SPY']) allTickers.push({t:'SPY', s:'ETF'});`
- Same G_HIST_CACHE approach; SPY history feeds into relative-strength calculations

**Shareable?** Yes — both already share the same SPY injection pattern. Saturday: verify whether SPY reliably lands in `G_HIST_CACHE` after enrichment or can be missed (e.g., when screener returns 0 results / static fallback path, SPY injection is skipped).

---

## Bug 5 — GO gate visibility (Panda-only)

**Panda location:**
- `scoreIt` GO decision: `index.html:16818` — `var isGo = total >= goThreshold && !avoidBad;`
- `goThreshold` default: `index.html:16810` — hardcoded `140`; reads `sc-minscore` input if present (lines 16813–16816)
- `avoidBad` in scoreIt set only from AVOID list: `index.html:16341`
- **Discrepancy:** `reclassifyGoThreshold` at `index.html:8711` uses a broader avoidBad check (same sign-flip as Bug 1), meaning the two GO-determination paths are not equivalent. A ticker can be `isGo=true` from `scoreIt` but then reclassified to `isGo=false` by `reclassifyGoThreshold` due to the Broken Trend false-positive.
- Prompt described gate as `score >= 110 AND fundScore >= 8 AND filtersPass AND (flow check)` — source of truth is simpler: just `total >= goThreshold && !avoidBad`. No fundScore gate, no filtersPass in the GO boolean itself (filtersPass is a separate field).

**RRJCAR location:** N/A — rrjcar uses a simpler single-threshold gate: `index.html:2492` — `var isGo = total >= 72 && !avoidBad;`

**Shareable?** No — Panda-specific divergence (different threshold, reclassify path, AVOID logic).

---

## Bug 6 — Score table sort

**Panda location:**
- `renderScan()`: `index.html:20161` — renders `G.filtered` (or text-searched subset) in whatever order the array is currently in
- `sortTable(col)`: `index.html:20121` — sorts `G.filtered` in-place by single column, then calls `renderScan()`
- `_resultRankCompare`: `index.html:16269` — multi-tier comparator: score → techScore → RS 5D → theme dailyScore → volume
- Default state: `G.sortCol='score', G.sortDir=-1` (`index.html:7953`), so header renders `SCORE ▼`
- **Root cause of out-of-order rows:** enrichment ticks (e.g., `index.html:15017`, 15039) call `G.results.sort(_resultRankCompare); G.filtered = excludedFilteredResults(); renderScan();` — this resets `G.filtered` from `G.results` (rank-compare order), silently overwriting any sort the user applied via `sortTable`. The header still shows `SCORE ▼` (correct initial default), but the underlying order is rank-compare (which ties-break beyond score alone). Tickers with equal scores are ordered by techScore/RS/theme/volume, making the table appear mis-sorted by score alone.

**RRJCAR location:** `renderScan` at `index.html:2923`; `sortTable` at `index.html:2915`
- rrjcar's `applyFilters` at line 2910 re-applies the current sort: `G.filtered.sort(function(a,b){ if(col==='ticker'||col==='sector') ... return G.sortDir*(a[col]-b[col]); });` — wait, that's `sortTable` not `applyFilters`. rrjcar's `applyFilters` at line 2910 just filters and calls `renderScan()` without re-sorting, same issue. However rrjcar's results table is smaller (no enrichment ticks resetting `G.filtered`) so the bug may not manifest.

**Shareable?** Partial — the fix (ensure enrichment ticks preserve user-applied sort, or use `_resultRankCompare` consistently and remove the per-column sort feature) would be Panda-specific, but the pattern is similar.

---

## Setup notes (Friday 2026-05-15)

- Panda repo cloned to: `C:\Users\Ruiz Family Laptop\scanner`
- rrjcar repo (read-only reference): `C:\Users\Ruiz Family Laptop\rrjcar-Terminal-v3`
- Working branch created: `weekend-scoring-fixes` (from `main`, clean, not pushed)
- Remote confirmed: `https://github.com/alexreed122287/scanner.git`
