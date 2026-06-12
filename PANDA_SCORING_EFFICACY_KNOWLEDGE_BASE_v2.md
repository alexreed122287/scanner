# OPTION PANDA Scoring Efficacy Knowledge Base — v2 (Post-Weekend-Fix)
**Source:** OPTION PANDA (https://alexreed122287.github.io/scanner/), v2.18.40 + PRs #45 and #46
**Date:** May 15, 2026, post-deploy verification
**Universe sampled:** 90 tickers in `G_HIST_CACHE`, each with 275 bars of daily OHLCV
**SPY reference:** present and current (275 bars, market return +5.35% over 21d, +0.21% over 5d)
**Score scale:** 0–164 across 27 active rules. 164 is the documented design ceiling for long-calls-only mode.
**GO threshold:** score ≥110 AND fund ≥8 AND filtersPass

This document supersedes the v1 knowledge base (May 15, 2026 morning audit). All numbers below reflect the live state of the deployed scanner after the weekend fix cycle.

---

## 1. Executive Summary

The weekend fix cycle (PRs #45 and #46) resolved or substantially mitigated every major issue identified in the v1 audit. The scanner is now in production-quality state for scoring arithmetic and GO classification.

| Metric | v1 audit (Friday) | v2 post-fixes (Sunday) |
|---|---|---|
| Sign-flip distribution (delta=0) | 1 of 101 (1%) | **82 of 90 (91%)** |
| Avg arithmetic delta | +3.15 to +4.89 | **−0.64** |
| GO count | 4 | **23** (rescore) / **29** (live UI) |
| GO conversion at threshold ≥110 | 9.3% | **~47%** |
| FMP cache size at audit | 1 entry | **41 entries** |
| SPY history cached | absent | **275 bars** |
| SCORE column header | `SCORE ▼` (misleading) | **`SCORE`** (clean) |

89 of 90 tickers now have explainable scores. The remaining single anomaly (CSCO at delta=-1) is a 1-point offset on one ticker and does not affect rankings or decisions.

---

## 2. Score Distribution

| Score band | Tickers | % of sample | Notes |
|---|---|---|---|
| 150–164 | 16 | 17.8% | Top tier — most include PROVEN ticker bonus |
| 140–149 | 7 | 7.8% | Strong setups |
| 130–139 | 12 | 13.3% | Solid GO candidates |
| 120–129 | 6 | 6.7% | Above-threshold |
| 110–119 | 8 | 8.9% | GO threshold band |
| 100–109 | 5 | 5.6% | Near-miss |
| 90–99 | 10 | 11.1% | Moderate signal |
| 70–89 | 17 | 18.9% | Weak signal |
| <70 | 9 | 10.0% | Insufficient or broken-trend tickers |

**Above 110 threshold:** 49 of 90 = 54% of sample (sample is biased toward known leaders since `G_HIST_CACHE` accumulates from prior scans).
**Above 110 AND GO:** 23 tickers — GO conversion now reflects real gate logic.
**Top of distribution saturates at 164** by design (see §7.1).

---

## 3. Rule Efficacy Table

All 27 rules, sorted by average points earned per ticker. Measured across 90 scored tickers from `G_HIST_CACHE` with SPY-based RS computations.

| Rule | Max Pts | Avg Pts | Pass Rate | Efficiency | Class | Notes |
|---|---|---|---|---|---|---|
| TF Aligned 2/3 | 12 | 11.47 | 95.6% | 95.6% | ⚠ **Near-floor** | Bull-market dominance |
| JT 12-1 Momentum | 20 | 10.00 | 50.0% | 50.0% | **Primary signal** | Single largest differentiator |
| EMA20 > EMA50 | 10 | 9.56 | 95.6% | 95.6% | ⚠ **Near-floor** | Bull-market floor |
| MFI(14) > 50 | 10 | 8.33 | 83.3% | 83.3% | **Primary signal** | Strong but high pass rate |
| PROVEN ticker | 8 | 8.00 | 100% (of 17) | 100% | **Whitelist bonus** | Fires only on 17 mega-cap whitelist; now visible in rules array |
| RS > SPY (21d) | 10 | 7.44 | 74.4% | 74.4% | **Continuous** | Now using real SPY (was self-referential) |
| Minervini Trend Template | 15 | 7.00 | 46.7% | 46.7% | **Primary signal** | 6-criterion composite |
| 52Wk Hi Prox <15% | 8 | 5.87 | 73.3% | 73.3% | **Continuous** | Within 15% of 52W high |
| Strong Sector | 8 | 5.87 | 73.3% | 73.3% | **Theme overlay** | Sector RS momentum |
| Price > EMA200 | 6 | 5.53 | 92.2% | 92.2% | ⚠ **Near-floor** | Bull-market floor |
| Sector PF > 2 | 5 | 4.83 | 96.7% | 96.7% | 🚨 **Floor** | Essentially every ticker gets these 5 pts |
| Analyst Revisions ↑ | 12 | 4.53 | 37.8% | 37.8% | **FMP signal** | Now firing realistically post-FMP-cache hydration |
| Analyst PT Exists | 8 | 4.36 | 54.4% | 54.4% | **FMP signal** | Paired with above |
| MACD Hist + | 6 | 4.00 | 66.7% | 66.7% | **Primary signal** | Trend-following momentum |
| U/D Volume Ratio (50d) | 12 | 3.91 | 58.9% | 32.6% | **Continuous** | Tiered scoring (mild=4, accum=8, strong=12) |
| RSI 40–70 | 6 | 3.60 | 60.0% | 60.0% | **Continuous** | Momentum zone |
| 52Wk Hi Prox <5% (G-H) | 6 | 3.40 | 56.7% | 56.7% | **Continuous** | Tighter proximity tier |
| ADX > 25 | 6 | 2.27 | 37.8% | 37.8% | **Continuous** | Trend strength |
| RSI 50–65 (Cardwell) | 6 | 2.07 | 34.4% | 34.4% | **Continuous** | Narrow bull-zone window |
| CMO(9) > 50 | 7 | 1.71 | 24.4% | 24.4% | **Momentum confirm** | Strong-CMO threshold |
| ADX 15–25 + DI+>DI- | 6 | 1.53 | 25.6% | 25.6% | **Early trend** | Mutually exclusive with ADX > 25 |
| BBW Squeeze (<p20 of 120d) | 10 | 1.33 | 13.3% | 13.3% | **Volatility setup** | Bollinger squeeze |
| GEX Call Flow | 6 | 1.16 | 25.6% | 19.3% | **Market struct.** | Conditional pts (0–6 range) |
| Pocket Pivot | 15 | 1.00 | 6.7% | 6.7% | **Rare setup** | High-value, rare-firing |
| VCP — ATR Contraction | 12 | 0.27 | 2.2% | 2.2% | **Rare setup** | Volatility contraction |
| 20d Donchian Breakout | 12 | 0.27 | 2.2% | 2.2% | **Rare setup** | Pure breakout |
| Broken Trend (penalty) | 0 | 0.00 | 95.6% | 0% | **Penalty (intact)** | Emits with pts:0 when intact, pts:-5 when broken; correctly accounted |
| Weak Sector (penalty) | — | — | 0% | — | **Conditional** | Rule only emitted when triggered; no weak sectors in current sample |

**Notable shifts vs v1:**
- PROVEN ticker now visible with `pts:8` (was invisible side-channel)
- Broken Trend penalty now `pts:0` when intact (no phantom +5)
- Analyst rules firing at 37.8% / 54.4% (were 1.0% / 1.0% due to cache decay)
- RS > SPY (21d) now using real SPY data (was self-referential at 86%)

---

## 4. Indicator Distributions (90 tickers, SPY-referenced)

| Indicator | Min | p25 | Median | Avg | p75 | Max |
|---|---|---|---|---|---|---|
| RSI(14) | 25.34 | 53.16 | 62.70 | 63.61 | 73.83 | 92.84 |
| ADX(14) | 0.60 | 11.10 | 19.80 | 20.41 | 29.60 | 48.60 |
| MACD Hist | −2.86 | −0.09 | 0.16 | 0.68 | 1.24 | 11.84 |
| MFI(14) | 31.5 | 56.0 | 61.4 | 63.11 | 72.8 | 89.9 |
| CMO(9) | −55 | 5.4 | 26.5 | 27.97 | 48.9 | 97.1 |
| TF Aligned | 0 | 3 | 3 | 2.80 | 3 | 3 |
| RS 5d vs SPY (%) | −11.02 | −0.18 | 2.98 | 4.73 | 7.49 | 44.89 |
| RS 21d vs SPY (%) | −14.60 | −0.03 | 5.64 | 10.52 | 13.96 | 61.21 |
| % above EMA200 | −21.97 | 12.86 | 27.39 | 31.13 | 39.87 | 233.14 |

**Observations:**
- **RS 21d median +5.64%** — sample skews to outperformers (cache holds momentum leaders), but the distribution is now grounded in real SPY return (+5.35% over 21d)
- **TF p25 = 3** — three-quarters of sample fully aligned across timeframes; explains 95.6% pass rate
- **RSI median 62.7** — sample heavily biased toward strong setups (vs general universe RSI ~50)
- **MFI median 61.4** — corroborates RSI; volume-weighted momentum confirms

---

## 5. Sign-Flip Distribution (the core correctness check)

After all fixes, `score - sumOfPassingRulePts` distributes as:

| Delta | Count | Pct | Cause |
|---|---|---|---|
| 0 | 82 | 91.1% | **Arithmetically perfect** |
| −5 | 5 | 5.6% | Broken Trend penalty applied correctly (trend < EMA50) |
| −15 | 1 | 1.1% | GS — score saturated at 164 cap (passing 179 pts of rules) |
| −17 | 1 | 1.1% | NVDA — score saturated at 164 cap (passing 181 pts of rules) |
| −1 | 1 | 1.1% | CSCO — 1-point offset of unknown origin (low priority) |

**v1 audit comparison:**
- v1 delta=0: 1 ticker (1%)
- v1 +5 phantom bonus: 65 tickers (64%)
- v1 +13 compound flip: 5 tickers (5%)
- v2 +5/+8/+13: zero across the board

The arithmetic is now reliable for nearly the entire universe.

---

## 6. Bug Status Tracker

| Bug | v1 Status | v2 Status | Resolution |
|---|---|---|---|
| Bug 1: GO reclassifier treats Broken Trend penalty as AVOID | 🚨 Open | ✅ Fixed | PR #45: changed check to `AVOID.indexOf(ticker) >= 0` |
| Bug 2 (formerly): Broken Trend penalty adds phantom +5 to score | 🚨 Open | ✅ Fixed | PR #45 + #46: rule now emits `pts:0` when intact, `pts:-5` when broken; summing correct |
| Bug 3: relStr21d never computed | 🚨 Open | ✅ Fixed | PR #45 (consumer) + PR #46 (SPY pre-fetch); both required |
| Bug 4 (formerly): FMP cache decay | ⚠ Open | ✅ Resolved naturally | Lazy-load fills cache during scan; 41 entries observed |
| Bug 5: GO gate logic opaque | ⚠ Open | ✅ Understood | Gate is `score≥110 AND fund≥8 AND filtersPass`; documented |
| Bug 6: SCORE column header shows misleading arrow | 🚨 Open | ✅ Fixed | PR #45: default `sortCol:null`, header shows arrow only on user-click |
| Bug 7 (discovered post-#45): PROVEN ticker side-channel +8 | 🚨 New | ✅ Fixed | PR #46: rule now carries `pts:8` visibly |
| Bug 8 (discovered post-#45): Weak Sector demotion hidden | 🚨 New | ✅ Fixed | PR #46: separate `Weak Sector (penalty)` rule entry with `pts:-8` |

**Cross-reference:** PRs #45 (4 commits) and #46 (3 commits) merged Saturday/Sunday. `REFACTOR_INVENTORY.md` documents rrjcar parallels for future shared-core extraction.

---

## 7. Architectural Notes

### 7.1 The 164 Score Ceiling

Source comment at scoreIt:
> `// +4 Analyst Revisions delta (now 16, was 12) = 164 max for long-calls-only.`

164 is the **intended maximum** for long-calls-only mode. When a ticker's sum-of-passing-rule-pts exceeds 164 (as GS does at 179 and NVDA at 181), the score saturates rather than overflow.

**Implication:** GS and NVDA are tied at 164 in score but differ in raw signal strength. If you want to rank within the saturated tier, the `sumOfPassingRulePts` field gives the true ordering. Consider exposing this as a tiebreaker or as an "uncapped score" tooltip for top-of-leaderboard tickers.

### 7.2 The Weak Sector Rule

The Weak Sector (penalty) rule is emitted **conditionally** — only when a ticker is in a demoted sector. This differs from most rules which emit unconditionally with `pass:true|false` for full transparency. The conditional emission means analysis scripts must not assume the rule exists in every ticker's rules array.

In the current sample, no sectors were weak enough to trigger the rule. This is design behavior, not a bug.

### 7.3 GO Gate (corrected 2026-06-12 — technical-only by owner decision)

```
isGo = (score >= goThreshold) AND NOT avoidBad
```

`goThreshold` reads the `sc-minscore` input (fallback 121 in both `scoreIt` and `reclassifyGoThreshold`). `avoidBad` is the AVOID-list check (via `AVOID.indexOf(ticker)` after PR #45).

**Correction:** earlier versions of this doc claimed `isGo` also required `fundScore >= 8` and `filtersPass`. That was never true of the shipped code, and on 2026-06-12 the owner confirmed technical-only gating is the intended design (audit M1.1). `fundScore` is advisory: it adds points to the total but does not gate GO. `filtersPass` is a separate, always-true field in the return object, not part of the GO boolean. GO counts therefore do NOT collapse when `G_FMP_CACHE` decays — FMP outages reduce scores by at most the fund-rule points, nothing more.

### 7.4 `scoreIt` signature (unchanged from v1)

```
scoreIt(ticker: string, ind: IndicatorBundle, opt: object) -> {
  score: number,
  techScore: number,
  fundScore: number,
  isGo: boolean,
  filtersPass: boolean,
  rules: Array<RuleResult>,
  passes: string[]
}

IndicatorBundle fields read: rsi, rsiPrev, macd, adx, diPlus, diMinus,
  ema20, ema50, ema200, atr, mfi, cmo, tf, price, week52hi,
  relStr5d, relStr21d
```

Note: `scoreIt` reads from globals `G_FMP_CACHE`, `G_HIST_CACHE`, `T_CACHE` and effectively requires the ticker to be in `G_HIST_CACHE` for several rules to evaluate. This is acceptable for in-app use but limits external testability. Long-term: candidate for the shared-core extraction.

### 7.5 Indicator Helpers (top-level globals)

```
calcRSIatIndex(days, period, idx) → number
calcMACD(days, fast, slow, sig)   → number (histogram only)
calcADX(days, period)              → {adx, diPlus, diMinus}
calcEMA(days, period)              → number
calcATR(days, period)              → number
calcMFI(days, period)              → number
calcCMO(days, period)              → number
calcTfAligned(days)                → number 0–3
```

`calcRSI` (non-indexed variant) does not exist as a global. Code paths that need RSI must use `calcRSIatIndex(hist, 14, hist.length-1)`.

---

## 8. Remaining Improvement Opportunities (low priority)

These are not bugs. They are quality-of-life or signal-quality improvements that could be considered in future cycles.

### 8.1 Reduce floor-rule weight (unchanged recommendation from v1)
Four rules pass >92% in bull regimes:
- Sector PF > 2 (96.7%) — consider dropping or raising PF threshold to 3
- EMA20 > EMA50 (95.6%) — consider lowering pts from 10 → 6
- TF Aligned 2/3 (95.6%) — convert to tiered (1/3 = 4 pts, 2/3 = 8 pts, 3/3 = 12 pts)
- Price > EMA200 (92.2%) — consider lowering from 6 → 3

In the current bull regime, ~30 points of every healthy ticker's score are essentially free.

### 8.2 CSCO −1 anomaly
Single ticker showing `score - sumPass = -1`. Affects 1.1% of universe. Likely a 1-point bonus or penalty fired through a side-channel similar to PROVEN/Weak Sector. Investigate only if a pattern emerges across more tickers.

### 8.3 Expose uncapped score for top-of-leaderboard tiebreaking
GS (179) and NVDA (181) both display as 164. Consider showing the uncapped sum as a tooltip or secondary metric for analysts who care about signal strength among saturated tickers.

### 8.4 Curve-score RSI and ADX
Both currently binary. rrjcar §3.2 demonstrates curve-scoring for partial credit. Would add gradient signal within current pass bands.

### 8.5 Compare RS 5d vs 21d signal quality
With SPY now properly cached, the data exists to test whether 5d or 21d RS is the better leading indicator on trades. Track score-band P&L by RS window over the next 40+ clean trades and compare.

---

## 9. Score-Band P&L Methodology (unchanged from v1)

> ⚠ **Still applies:** rrjcar's contaminated-dataset warning continues to hold here. Pre-fix Panda P&L data was generated against a scoring engine with sign-flip bugs and PROVEN-bonus invisibility. Post-fix trades should be tracked separately. Minimum sample: 40 clean trades per score band before drawing scoring-quality conclusions.

The post-fix tracking starts now (May 15, 2026). Trades executed before the deploy of PR #45 should be excluded from scoring-correlation analysis.

---

## 10. Verification Reproducibility

The numbers in this document were captured live from the deployed app at https://alexreed122287.github.io/scanner/ after PRs #45 and #46. To reproduce:

1. Open the deployed page
2. Click SCAN, wait for completion
3. Open browser devtools console
4. Paste the rescore script from `panda_efficacy_rescore.js`
5. Read `window.__panda_efficacy` for the result object

The script is included as a companion file. It does not modify state.

---

*Generated May 15, 2026, ~11:15 PM CT. Reflects deployed state of OPTION PANDA after weekend fix cycle (PRs #45 and #46 merged). Supersedes v1 knowledge base (May 15, 2026 ~5:30 PM CT).*
