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

## Bug A — Broken Trend penalty pts metadata inconsistency

**Panda location:** `index.html:16796` — rule entry (after Bug A fix):
```js
res.push({n:'Broken Trend (penalty)', pass:!brokenTrend, val:brokenTrendVal, filter:false, pts:0, isPenalty:true});
```
The actual score deduction is applied inline above this line: `if(brokenTrend){ score-=5; techScore-=5; }`. The `pts` field is pure metadata used by audit/display code (e.g., `rules.filter(r=>r.pass).map(r=>r.pts).reduce(sum)`). Before the fix, `pts:-5` on the rule entry with `pass:true` for intact-trend tickers caused `sumPassPts` to undercount by 5 — making `score - sumPassPts = +5` for 83% of the universe. Score values were always correct; only the pts metadata was wrong.

**RRJCAR cross-check:** No Broken Trend rule in rrjcar. Grepped for `isPenalty` — zero matches. The only score deduction in rrjcar is `score -= 15` for AVOID-listed tickers (inline at `index.html:2424`). No negative-pts rule entries exist. Bug A does not exist in rrjcar.

**Shareable?** No — Panda-specific rule and pattern. Not a candidate for shared-core extraction.

---

## Bug B — SCORE ▼ default arrow on unsorted table

**Panda location:** `index.html:7953` — `G` state init:
```js
// BEFORE: sortCol:'score',sortDir:-1
// AFTER:  sortCol:null,sortDir:-1
```
`renderScan` reads `G.sortCol` to decide which header gets an arrow. Default `'score'` showed `▼` even though rows are ordered by `_resultRankCompare` (multi-tier: score → techScore → RS → theme → volume), not a flat score sort. Changed to `null` so no arrow shows until user explicitly clicks a column. A new `_reapplySort()` helper preserves user-applied sorts across bg-enrichment ticks that reset `G.filtered`.

**RRJCAR cross-check:** `index.html:1267` — `var G={...,sortCol:'score',sortDir:-1,...}` — the same bug is present in rrjcar. The fix (change default to `sortCol:null`, add `_reapplySort()` after enrichment resets) applies directly. rrjcar's enrichment loop is simpler (no bg-enrich tick resetting G.filtered), so only the default needs to change.

**Shareable?** Yes — the `sortCol:null` default fix is a one-line change applicable to rrjcar immediately. The `_reapplySort()` helper may not be needed in rrjcar if its enrichment path doesn't reset `G.filtered`.

---

## Fix 1 (followup) — SPY history pre-fetch to activate relStr21d

**Panda location:** `index.html` — foreground enrichment setup in `runScan`. SPY is added to the dynamic screener universe (`index.html:18772`) but typically ranks outside `SC_ENRICH_LIMIT` (60), so `fetchIndicatorHistory('SPY')` was never called during a normal scan. `G_HIST_CACHE['SPY']` stayed `undefined`, making the `relStr21d` computation in `scoreIt` a no-op on every scan. Fix: fire-and-forget `fetchIndicatorHistory('SPY')` just before the enrichment queue starts (immediately after `fmpKey` resolution), independent of SPY's rank.

**RRJCAR cross-check:** rrjcar has no `G_HIST_CACHE`, no `fetchIndicatorHistory`, and no `relStr21d` computation. SPY appears only as a sim-quote price seed (`baseMap.SPY`). Not applicable.

**Shareable?** No — Panda-specific architecture (G_HIST_CACHE + relStr21d). When rrjcar adopts indicator history, this pattern should be carried over.

---

## Fix 2 (followup) — PROVEN ticker rule missing pts field

**Panda location:** `index.html:16344` — before fix:
```js
if(provenOk){ score += 8; techScore += 8; res.push({n:'PROVEN ticker', pass:true, val:'+8pts', filter:false}); }
```
`pts` field absent → `undefined`. Score correctly adds +8 inline, but `rules.filter(r=>r.pass).map(r=>r.pts).reduce(sum)` contributes `NaN` (or 0 if guarded), leaving `score - sumPassPts = +8` for all 12 PROVEN tickers. Fix: add `pts:8` to the rule entry.

Also fixed: **Weak Sector penalty** (`index.html:16801`). The Strong Sector rule applied `score -= 8` inline for `combo <= 25` but emitted `pass:false` on the rule entry, making the -8 invisible to the audit sum. Added a separate `{n:'Weak Sector (penalty)', pass:true, pts:-8}` entry so the deduction is accounted for. Strong Sector's `pass` remains `false` for demoted tickers, preserving `_RULE_TIERS.trend` conviction counting.

**RRJCAR cross-check:** `index.html:2425` — same pattern:
```js
if(provenOk){ score += 8; techScore += 8; res.push({n:'PROVEN ticker', pass:true, val:'+8pts', filter:false}); }
```
Same missing `pts` field. rrjcar has no Strong Sector / Weak Sector rule, so no parallel for the sector penalty fix. PROVEN ticker fix is a one-line change applicable to rrjcar immediately.

**Shareable?** Yes — PROVEN ticker `pts:8` fix is identical in both codebases. Strong Sector is Panda-only.

---

## Setup notes (Friday 2026-05-15)

- Panda repo cloned to: `C:\Users\Ruiz Family Laptop\scanner`
- rrjcar repo (read-only reference): `C:\Users\Ruiz Family Laptop\rrjcar-Terminal-v3`
- Working branch created: `weekend-scoring-fixes` (from `main`, clean, not pushed)
- Remote confirmed: `https://github.com/alexreed122287/scanner.git`
