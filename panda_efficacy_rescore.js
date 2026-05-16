// PANDA SCORING EFFICACY — re-scoring analysis script
// Paste into Chrome devtools console at https://alexreed122287.github.io/scanner/
// Requires: G_HIST_CACHE populated (run a scan first), scoreIt and calc* helpers in global scope.

(() => {
  const tickers = Object.keys(window.G_HIST_CACHE);
  if (!tickers.length) { console.error('G_HIST_CACHE empty — run a scan first.'); return null; }

  const ruleAgg = {};
  const scored = [];
  let skipped = 0, errors = 0;

  // SPY reference (falls back to self-return if SPY not cached)
  const spyHist = window.G_HIST_CACHE['SPY'];
  let spy5d = 0, spy21d = 0;
  if (spyHist && spyHist.length > 22) {
    const N = spyHist.length;
    spy5d  = (spyHist[N-1].close - spyHist[N-6].close)  / spyHist[N-6].close  * 100;
    spy21d = (spyHist[N-1].close - spyHist[N-22].close) / spyHist[N-22].close * 100;
  } else {
    console.warn('SPY not in G_HIST_CACHE — RS values use self-return as fallback.');
  }

  for (const sym of tickers) {
    const hist = window.G_HIST_CACHE[sym];
    if (!Array.isArray(hist) || hist.length < 50) { skipped++; continue; }
    const N = hist.length;
    const last = hist[N-1];
    try {
      const adxObj = window.calcADX(hist, 14) || {};
      const week52hi = Math.max(...hist.slice(-Math.min(252, N)).map(b => b.high));
      const t5d  = (last.close - hist[N-6].close)  / hist[N-6].close  * 100;
      const t21d = N>=22 ? (last.close - hist[N-22].close) / hist[N-22].close * 100 : 0;
      const ind = {
        price: last.close,
        rsi: window.calcRSIatIndex(hist, 14, N-1),
        rsiPrev: window.calcRSIatIndex(hist, 14, N-2),
        macd: window.calcMACD(hist, 12, 26, 9),
        adx: adxObj.adx, diPlus: adxObj.diPlus, diMinus: adxObj.diMinus,
        ema20: window.calcEMA(hist, 20),
        ema50: window.calcEMA(hist, 50),
        ema200: window.calcEMA(hist, 200),
        atr: window.calcATR(hist, 14),
        mfi: window.calcMFI(hist, 14),
        cmo: window.calcCMO(hist, 9),
        tf: window.calcTfAligned(hist),
        week52hi,
        relStr5d: t5d - spy5d,
        relStr21d: t21d - spy21d
      };
      const r = window.scoreIt(sym, ind, {});
      if (!r || !r.rules) { errors++; continue; }
      const sumPass = r.rules.filter(x => x.pass).reduce((s,x) => s + (x.pts || 0), 0);
      scored.push({
        sym, score: r.score, tech: r.techScore, fund: r.fundScore,
        isGo: r.isGo, filtersPass: r.filtersPass,
        sumPass, signFlipDelta: r.score - sumPass,
        passes: r.passes
      });
      r.rules.forEach(rule => {
        const k = rule.n;
        if (!ruleAgg[k]) ruleAgg[k] = { fires: 0, ptsEarned: 0, maxPts: 0, total: 0 };
        ruleAgg[k].total++;
        ruleAgg[k].maxPts = Math.max(ruleAgg[k].maxPts, rule.pts || 0);
        if (rule.pass) {
          ruleAgg[k].fires++;
          ruleAgg[k].ptsEarned += (rule.pts || 0);
        }
      });
    } catch (e) { errors++; }
  }

  // Build rule summary
  const ruleSummary = Object.entries(ruleAgg).map(([n, v]) => ({
    rule: n,
    maxPts: v.maxPts,
    passRate: +(v.fires * 100 / v.total).toFixed(1),
    avgPts: +(v.ptsEarned / v.total).toFixed(2),
    efficiency: v.maxPts ? +(v.ptsEarned * 100 / (v.total * Math.max(v.maxPts, 1))).toFixed(1) : 0,
    fires: v.fires, total: v.total
  })).sort((a, b) => b.avgPts - a.avgPts);

  // Score bands
  const bands = { '<70':0, '70-89':0, '90-99':0, '100-109':0, '110-119':0, '120-129':0, '130-139':0, '140-149':0, '150+':0 };
  scored.forEach(t => {
    const s = t.score;
    if (s < 70)        bands['<70']++;
    else if (s < 90)   bands['70-89']++;
    else if (s < 100)  bands['90-99']++;
    else if (s < 110)  bands['100-109']++;
    else if (s < 120)  bands['110-119']++;
    else if (s < 130)  bands['120-129']++;
    else if (s < 140)  bands['130-139']++;
    else if (s < 150)  bands['140-149']++;
    else               bands['150+']++;
  });

  // Sign-flip detection
  const signFlipDist = {};
  scored.forEach(t => { signFlipDist[t.signFlipDelta] = (signFlipDist[t.signFlipDelta] || 0) + 1; });

  const result = {
    universe: scored.length,
    skipped, errors,
    scoreBands: bands,
    goCount: scored.filter(t => t.isGo).length,
    aboveThreshold110: scored.filter(t => t.score >= 110).length,
    signFlipDistribution: signFlipDist,
    avgSignFlipDelta: scored.reduce((s,t) => s + t.signFlipDelta, 0) / scored.length,
    fmpCoverage: {
      hits: scored.filter(t => t.fund > 0).length,
      misses: scored.filter(t => t.fund === 0).length
    },
    ruleSummary,
    topByScore: scored.slice().sort((a,b) => b.score - a.score).slice(0, 20),
    allScored: scored
  };

  console.table(ruleSummary);
  console.table(result.topByScore.map(t => ({ sym: t.sym, score: t.score, tech: t.tech, fund: t.fund, sumPass: t.sumPass, delta: t.signFlipDelta, isGo: t.isGo })));
  console.log('Score bands:', bands);
  console.log('Sign-flip distribution:', signFlipDist);
  window.__panda_efficacy = result;
  return result;
})();
