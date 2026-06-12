#!/usr/bin/env node
// ─────────────────────────────────────────────────────────────────────────────
// score.test.js — unit tests over the trade-decision core (audit M0.1/M0.2).
//
// Evaluates every <script> block from index.html inside a Node `vm` sandbox
// with stubbed browser globals, then asserts on the PURE functions: scoreIt,
// calcEMA, calcMACD, calcADX, calcPnlAtPrice, universeLookup, plus
// source-introspection guards for the GO gate and the auto-trader safety
// gates (same pattern as the runtime health checks, but executable in CI).
//
// Run:  node --test tools/audit/score.test.js
// CI :  .github/workflows/unit-tests.yml
//
// Covered regression classes (audit §3.3/§3.4):
//   - GO gate is technical-only (owner decision 2026-06-12, M1.1) — both paths
//   - _synth clear threshold + ind._bars depth stamp (M1.2)
//   - calcEMA short-data degradation (documented behavior, T2)
//   - option P&L intrinsic math (T5 baseline)
//   - score === Σ(rule pts) invariant
//   - threshold-fallback parity (T4)
// ─────────────────────────────────────────────────────────────────────────────
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const { execSync } = require('child_process');

// ── 1. Extract <script> blocks (reuses the static-analysis extractor) ──────
execSync('node ' + JSON.stringify(path.join(__dirname, 'extract-scripts.js')), { stdio: 'pipe' });
const code = fs.readFileSync(path.join(__dirname, 'extracted-scripts.js'), 'utf8');

// ── 2. Browser-global stubs ─────────────────────────────────────────────────
function makeClassList() {
  return { add() {}, remove() {}, toggle() {}, contains() { return false; } };
}
function makeEl() {
  const store = { value: '', textContent: '', innerHTML: '', checked: false, disabled: false };
  const el = new Proxy(store, {
    get(t, p) {
      if (p in t) return t[p];
      if (p === 'style') return (t._style || (t._style = {}));
      if (p === 'classList') return (t._cl || (t._cl = makeClassList()));
      if (p === 'dataset') return (t._ds || (t._ds = {}));
      if (p === 'children' || p === 'options') return [];
      if (p === 'querySelectorAll' || p === 'getElementsByClassName' || p === 'getElementsByTagName') return () => [];
      if (p === 'querySelector' || p === 'appendChild' || p === 'insertBefore' || p === 'cloneNode' || p === 'closest') return () => makeEl();
      if (p === 'getAttribute') return () => null;
      if (p === 'getContext') return () => new Proxy({}, { get: () => () => {} });
      if (p === 'getBoundingClientRect') return () => ({ top: 0, left: 0, width: 0, height: 0, right: 0, bottom: 0 });
      if (typeof p === 'symbol') return undefined;
      return () => undefined; // any unknown method → no-op
    },
    set(t, p, v) { t[p] = v; return true; },
  });
  return el;
}

const localStorageStub = {
  _s: {},
  getItem(k) { return Object.prototype.hasOwnProperty.call(this._s, k) ? this._s[k] : null; },
  setItem(k, v) { this._s[k] = String(v); },
  removeItem(k) { delete this._s[k]; },
  key(i) { return Object.keys(this._s)[i] || null; },
  clear() { this._s = {}; },
  get length() { return Object.keys(this._s).length; },
};

const documentStub = new Proxy({}, {
  get(t, p) {
    if (p === 'getElementById' || p === 'createElement' || p === 'createElementNS' || p === 'querySelector') return () => makeEl();
    if (p === 'querySelectorAll' || p === 'getElementsByClassName' || p === 'getElementsByTagName') return () => [];
    if (p === 'body' || p === 'documentElement' || p === 'head') return makeEl();
    if (p === 'addEventListener' || p === 'removeEventListener' || p === 'createTextNode') return () => {};
    if (p === 'cookie') return '';
    if (p === 'visibilityState') return 'visible';
    if (p === 'readyState') return 'loading'; // keep DOMContentLoaded handlers queued, never fired
    if (p === 'hidden') return false;
    if (p === 'title') return '';
    if (typeof p === 'symbol') return undefined;
    return () => {};
  },
  set() { return true; },
});

const sandbox = {
  console,
  document: documentStub,
  localStorage: localStorageStub,
  sessionStorage: { getItem: () => null, setItem() {}, removeItem() {} },
  location: { href: 'https://localhost/', search: '', hash: '', hostname: 'localhost', protocol: 'https:', pathname: '/', origin: 'https://localhost', reload() {} },
  navigator: { userAgent: 'node-test', language: 'en-US', onLine: true, clipboard: { writeText: async () => {} }, serviceWorker: undefined, standalone: false, maxTouchPoints: 0 },
  history: { pushState() {}, replaceState() {}, back() {} },
  screen: { width: 1920, height: 1080 },
  matchMedia: () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }),
  setTimeout: () => 0, clearTimeout() {},
  setInterval: () => 0, clearInterval() {},
  requestAnimationFrame: () => 0, cancelAnimationFrame() {},
  requestIdleCallback: () => 0,
  fetch: () => Promise.resolve({ ok: false, status: 0, json: async () => ({}), text: async () => '' }),
  XMLHttpRequest: function () { return { open() {}, send() {}, setRequestHeader() {}, addEventListener() {} }; },
  alert() {}, confirm: () => false, prompt: () => null,
  Notification: { permission: 'denied', requestPermission: async () => 'denied' },
  MutationObserver: function () { return { observe() {}, disconnect() {} }; },
  ResizeObserver: function () { return { observe() {}, disconnect() {} }; },
  IntersectionObserver: function () { return { observe() {}, disconnect() {} }; },
  CustomEvent: function () {}, Event: function () {},
  Audio: function () { return { play: () => Promise.resolve(), pause() {} }; },
  Image: function () { return makeEl(); },
  performance: { now: () => Date.now() },
  atob: (s) => Buffer.from(s, 'base64').toString('binary'),
  btoa: (s) => Buffer.from(s, 'binary').toString('base64'),
  crypto: require('crypto').webcrypto,
  URL, URLSearchParams,
  Chart: undefined, echarts: undefined,
  innerWidth: 1920, innerHeight: 1080, devicePixelRatio: 1,
  addEventListener() {}, removeEventListener() {}, dispatchEvent() {},
  getComputedStyle: () => new Proxy({}, { get: () => '' }),
  scrollTo() {}, open() {}, focus() {}, blur() {},
  speechSynthesis: { speak() {}, cancel() {} },
  OneSignal: undefined, OneSignalDeferred: undefined, emailjs: undefined,
};
sandbox.window = sandbox;
sandbox.self = sandbox;
sandbox.globalThis = sandbox;
sandbox.top = sandbox;
sandbox.parent = sandbox;

vm.createContext(sandbox);
vm.runInContext(code, sandbox, { timeout: 60000, filename: 'extracted-scripts.js' });

// ── 3. Fixtures ─────────────────────────────────────────────────────────────
// Tradier daily-bar shape: {date, open, high, low, close, volume}
function mkBars(n, opts) {
  opts = opts || {};
  const start = opts.start != null ? opts.start : 100;
  const step = opts.step != null ? opts.step : 0; // per-bar close delta
  const vol = opts.volume != null ? opts.volume : 1e6;
  const bars = [];
  const d0 = new Date('2025-01-02');
  for (let i = 0; i < n; i++) {
    const close = start + step * i;
    const d = new Date(d0.getTime() + i * 864e5);
    bars.push({
      date: d.toISOString().slice(0, 10),
      open: close - Math.abs(step) / 2,
      high: close + Math.max(1, Math.abs(step)),
      low: close - Math.max(1, Math.abs(step)),
      close: +close.toFixed(4),
      volume: vol,
    });
  }
  return bars;
}

function baseInd(price) {
  // bulk-scan placeholder shape (CLAUDE.md "Scoring pipeline" step 1)
  return {
    rsi: 50, macd: 0, adx: 30, tf: 2,
    ema20: price * 0.99, ema50: price * 0.97, ema200: price * 0.93,
    atr: price * 0.015, price: price,
    volume: 2e6, avgVol: 1e6, changePct: 1.0,
  };
}

const { scoreIt, calcEMA, calcMACD, calcADX, calcPnlAtPrice, universeLookup,
        reclassifyGoThreshold, runAutoScanCycle, submitOrder,
        MIN_TRADE_BARS, AVOID, clamp } = sandbox;

// ── 4. Indicator math ───────────────────────────────────────────────────────
test('calcEMA: constant series converges to the constant', () => {
  const ema = calcEMA(mkBars(250, { start: 100, step: 0 }), 200);
  assert.ok(Math.abs(ema - 100) < 1e-6, 'EMA of flat 100s should be 100, got ' + ema);
});

test('calcEMA: short data degrades to mean of available closes (documented T2 behavior)', () => {
  const bars = mkBars(40, { start: 100, step: 1 }); // closes 100..139
  const ema = calcEMA(bars, 200);
  const mean = bars.reduce((s, b) => s + b.close, 0) / bars.length;
  assert.ok(Math.abs(ema - mean) < 1e-6,
    'calcEMA(<period bars) is documented to return the mean (' + mean + '), got ' + ema +
    '. If this fails, the degradation contract changed — update the bar-depth gate docs.');
});

test('calcMACD: accelerating uptrend yields positive histogram', () => {
  // A perfectly linear trend converges the histogram to 0 (constant EMA gap),
  // so use flat-then-rising: 200 flat bars, then 50 bars climbing — the fast
  // EMA pulls away from the slow EMA and the histogram goes positive.
  const flat = mkBars(200, { start: 100, step: 0 });
  const rising = mkBars(50, { start: 100, step: 1.5 });
  const macd = calcMACD(flat.concat(rising));
  assert.ok(typeof macd === 'number' && macd > 0, 'expected positive MACD hist, got ' + macd);
  // And the mirror: flat-then-falling must be negative.
  const falling = mkBars(50, { start: 100, step: -1.5 });
  const macdDown = calcMACD(flat.concat(falling));
  assert.ok(macdDown < 0, 'expected negative MACD hist on breakdown, got ' + macdDown);
});

test('calcADX: uptrend has DI+ > DI- and adx in [0,100]', () => {
  const r = calcADX(mkBars(250, { start: 50, step: 0.5 }), 14);
  assert.ok(r && typeof r.adx === 'number', 'calcADX should return {adx,...}');
  assert.ok(r.adx >= 0 && r.adx <= 100, 'adx out of range: ' + r.adx);
  assert.ok(r.diPlus > r.diMinus, 'uptrend should have DI+ > DI-');
});

// ── 5. Option P&L (intrinsic contract math) ─────────────────────────────────
test('calcPnlAtPrice: long call intrinsic P&L', () => {
  assert.strictEqual(calcPnlAtPrice(110, 100, 'CALL', 5, 1, 'BUY_TO_OPEN'), 500);
  assert.strictEqual(calcPnlAtPrice(95, 100, 'CALL', 5, 1, 'BUY_TO_OPEN'), -500); // OTM: lose premium
  assert.strictEqual(calcPnlAtPrice(110, 100, 'CALL', 5, 2, 'BUY_TO_OPEN'), 1000);
});

test('calcPnlAtPrice: long put + short call mirror correctly', () => {
  assert.strictEqual(calcPnlAtPrice(90, 100, 'PUT', 5, 1, 'BUY_TO_OPEN'), 500);
  assert.strictEqual(calcPnlAtPrice(110, 100, 'CALL', 5, 1, 'SELL_TO_OPEN'), -500);
});

// ── 6. scoreIt: synth lifecycle + bar-depth stamp (M1.2) ────────────────────
test('scoreIt: no history → _synth=true, _bars=0', () => {
  const ind = baseInd(100);
  sandbox.G_HIST_CACHE['__TESTNOHIST__'] = undefined;
  delete sandbox.G_HIST_CACHE['__TESTNOHIST__'];
  const r = scoreIt('__TESTNOHIST__', ind, {});
  assert.strictEqual(ind._synth, true, 'no-history row must stay _synth');
  assert.strictEqual(ind._bars, 0, 'no-history row must stamp _bars=0');
  assert.ok(typeof r.score === 'number' && typeof r.isGo === 'boolean');
});

test('scoreIt: 40-bar history clears _synth (≥30) but is below MIN_TRADE_BARS', () => {
  const ind = baseInd(120);
  sandbox.G_HIST_CACHE['__TEST40__'] = mkBars(40, { start: 100, step: 0.5 });
  const r = scoreIt('__TEST40__', ind, {});
  delete sandbox.G_HIST_CACHE['__TEST40__'];
  assert.strictEqual(ind._synth, false, '40 bars should clear _synth (threshold 30)');
  assert.strictEqual(ind._bars, 40, '_bars must reflect cached depth');
  assert.ok(MIN_TRADE_BARS === 100, 'MIN_TRADE_BARS expected 100, got ' + MIN_TRADE_BARS);
  assert.ok(ind._bars < MIN_TRADE_BARS, 'fixture must sit inside the shallow window');
  assert.ok(typeof r.score === 'number');
});

test('scoreIt: 280-bar history clears both _synth and the bar-depth gate', () => {
  const ind = baseInd(150);
  sandbox.G_HIST_CACHE['__TEST280__'] = mkBars(280, { start: 80, step: 0.25 });
  scoreIt('__TEST280__', ind, {});
  delete sandbox.G_HIST_CACHE['__TEST280__'];
  assert.strictEqual(ind._synth, false);
  assert.strictEqual(ind._bars, 280);
  assert.ok(ind._bars >= MIN_TRADE_BARS);
});

// ── 7. GO gate: technical-only (owner decision 2026-06-12, audit M1.1) ──────
test('GO gate: isGo === (score ≥ 121 fallback) && !AVOID — fundScore must NOT gate', () => {
  // DOM stub returns value:'' for sc-minscore → scoreIt falls back to 121.
  const fixtures = [
    { tk: '__TESTGO1__', bars: mkBars(280, { start: 50, step: 0.6, volume: 3e6 }), price: 217 },
    { tk: '__TESTGO2__', bars: mkBars(280, { start: 200, step: -0.3 }), price: 116 },
    { tk: '__TESTGO3__', bars: mkBars(40, { start: 100, step: 0.5 }), price: 120 },
  ];
  for (const f of fixtures) {
    const ind = baseInd(f.price);
    sandbox.G_HIST_CACHE[f.tk] = f.bars;
    const r = scoreIt(f.tk, ind, {});
    delete sandbox.G_HIST_CACHE[f.tk];
    const expected = (r.score >= 121) && AVOID.indexOf(f.tk) < 0;
    assert.strictEqual(r.isGo, expected,
      f.tk + ': isGo must equal (score>=121 && !avoid) regardless of fundScore (' +
      'score=' + r.score + ' fund=' + r.fundScore + ')');
  }
});

test('GO gate source guard: no fundScore condition in either GO path', () => {
  const s1 = scoreIt.toString();
  assert.match(s1, /isGo\s*=\s*total\s*>=\s*goThreshold\s*&&\s*!avoidBad\s*;/,
    'scoreIt isGo must be technical-only (owner decision 2026-06-12). ' +
    'If you intentionally changed the GO gate, get a fresh owner decision and update this test.');
  const s2 = reclassifyGoThreshold.toString();
  // (The word "fundScore" appears in guard COMMENTS — only the isGo
  // assignment itself is asserted.)
  assert.match(s2, /r\.isGo\s*=\s*\(r\.score\s*>=\s*thresh\)\s*&&\s*!avoidBad\s*;/,
    'reclassifyGoThreshold must mirror scoreIt exactly');
});

test('GO threshold fallback parity (audit T4): both paths fall back to 121', () => {
  assert.match(scoreIt.toString(), /goThreshold\s*=\s*121/, 'scoreIt fallback must be 121');
  const s = reclassifyGoThreshold.toString();
  assert.match(s, /:\s*121/, 'reclassify empty-input fallback must be 121');
  assert.match(s, /thresh\s*=\s*121/, 'reclassify NaN fallback must be 121');
  assert.ok(!/=\s*140/.test(s), 'stale 140 fallback must not return');
});

// ── 8. Score invariant: score === clamp(Σ all rule pts) ────────────────────
test('score === clamp(Σ pts over ALL emitted rules, 0, 156)', () => {
  const ind = baseInd(150);
  sandbox.G_HIST_CACHE['__TESTSUM__'] = mkBars(280, { start: 80, step: 0.25, volume: 2e6 });
  const r = scoreIt('__TESTSUM__', ind, {});
  delete sandbox.G_HIST_CACHE['__TESTSUM__'];
  const sum = r.rules.reduce((s, rl) => s + (rl.pts || 0), 0);
  assert.strictEqual(r.score, clamp(sum, 0, 156),
    'score must equal the clamped sum of every emitted rule pts (incl. penalties)');
});

// ── 9. Universe lookup (audit P1/QW1) ───────────────────────────────────────
test('universeLookup: UNIVERSE_FULL wins, falls back to UNIVERSE, rebuilds on mutation', () => {
  const probe = sandbox.UNIVERSE_FULL[0];
  assert.ok(probe && probe.t, 'UNIVERSE_FULL fixture sanity');
  assert.strictEqual(universeLookup(probe.t), probe, 'must return the UNIVERSE_FULL entry by identity');
  assert.strictEqual(universeLookup('__NOPE__'), undefined);
  sandbox.UNIVERSE_FULL.push({ t: '__TESTU__', s: 'Test sector' });
  assert.strictEqual(universeLookup('__TESTU__').s, 'Test sector', 'must rebuild after mutation');
  sandbox.UNIVERSE_FULL.pop();
});

// ── 10. Money-path safety gates stay in source (mirror of runtime checks) ───
test('auto-trader retains synth, sandbox, and bar-depth gates in source', () => {
  const src = runAutoScanCycle.toString();
  assert.ok(src.indexOf('_synth') >= 0, 'synth gate stripped from runAutoScanCycle');
  assert.ok(src.indexOf('_autoSandbox') >= 0, 'sandbox gate stripped from runAutoScanCycle');
  assert.ok(src.indexOf('MIN_TRADE_BARS') >= 0 && src.indexOf('_bars') >= 0,
    'bar-depth gate (M1.2) stripped from runAutoScanCycle');
});

test('submitOrder retains sandbox refusal in source', () => {
  const src = submitOrder.toString();
  assert.ok(/SANDBOX (mode|gate)/.test(src), 'submitOrder sandbox refusal stripped');
});
