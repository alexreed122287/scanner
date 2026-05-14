# Data Liveness & Synthetic-Data Safety — Knowledge Base

A working playbook for the problem **"prove every visible element in this app is real, live data — not a placeholder, not stale, not synthetic, not silently failed."** Distilled from a multi-PR effort on a single-page-app trading scanner.

Drop this file into a new project and the patterns transfer with light adaptation. The starter prompt at the end can seed a new Claude session.

---

## 0. The problem in one line

> An app that *looks* like it's showing live data, but actually a chain of fallbacks → placeholders → simulated values can render plausible-looking numbers all the way to the user with no warning.

The bug isn't "the data is wrong." The bug is **"the system can't tell when the data is wrong."** Every fix in this playbook restores the ability to know.

### Symptoms that suggest you have this problem

- Some rule / signal / score fires on *every* row identically (e.g. every ticker passes "RSI between 40-70" because RSI defaults to 50).
- A page reload shows different numbers than a freshly-loaded scan — but the cache is "still valid."
- Auto-submit / auto-trade / auto-anything works in dev but you can't tell what data it acted on.
- Sandbox/demo mode is visually indistinguishable from production mode.
- Bug reports take the form "this number is weird" rather than "this is broken" — because the system is *almost* right.

---

## 1. Why placeholders are the root pathology

Apps with multi-tier fallbacks usually have these layers:

```
  ┌────────────────────────────────┐
  │ live data path (API)           │  ← what should run
  ├────────────────────────────────┤
  │ cache layer (in-memory)        │  ← speed
  ├────────────────────────────────┤
  │ cache layer (localStorage)     │  ← survive reload
  ├────────────────────────────────┤
  │ placeholder constants          │  ← cold start / partial enrichment
  ├────────────────────────────────┤
  │ pure-sim functions             │  ← no API key configured
  └────────────────────────────────┘
```

Each lower layer exists to keep the app from breaking when the upper layer is unavailable. That's correct design. **The bug is when a lower layer silently impersonates a higher layer**, so the user (and the code) believes they're acting on live data when they aren't.

Concrete examples we hit:

| Layer | What it stamps | Pretends to be |
|---|---|---|
| Bulk-scan init | `ind.rsi = 50`, `ind.adx = 30`, `ind.macd = 0`, `ind.ema20 = price*0.99` | Live indicators |
| `simInd` (no API key) | Random RSI 32–78, random ADX, random EMA ratios | Live indicators |
| `simOpt` (no chain) | Random Greeks, OI, IV | Live options chain |
| `simQuote` (no quotes) | Hardcoded base price × random multiplier | Real quote |
| Cache restore | Whatever the last write was | A fresh fetch |
| Background enrichment (in-progress) | Top-60 done, ranks 61-200 still on bulk-init placeholders | Fully enriched scan |

All of these are necessary fallbacks. The fix isn't to remove them — it's to **flag them**.

---

## 2. The three-artifact pattern

The deliverable that closes this bug class is three things that all share one definition:

```
   HEALTHCHECK.md  ←→  window.opHealthCheck()  ←→  UI panel button
        ↑                      ↑                       ↑
   acceptance criteria    runtime registry      user-visible state
   (markdown table)      (function in code)    (button + table)
```

### 2a. `HEALTHCHECK.md` — the acceptance-criteria contract

A per-tab table, one row per visible data element:

| Element | DOM selector | JS setter | Data source | Pass-fail predicate |
|---|---|---|---|---|
| SPY quote | `#h-spy` | `updateHeaderQuotes` (line ~26905) | `Tradier /v1/markets/quotes` | `el.textContent !== '--' && parseFloat(el.textContent) > 0` |

The doc is the source of truth. The function below mirrors it.

### 2b. `window.opHealthCheck()` — runtime check registry

A registry of plain objects:

```js
var CHECKS = [
  { tab:'hdr', label:'SPY quote', sev:'important', fn:function(){
      var el = document.getElementById('h-spy'); if(!el) return 'n/a';
      var s = (el.textContent || '').trim();
      return s !== '--' && !isNaN(parseFloat(s));
  }},
  // ... 70+ more
];
```

Each `fn` returns one of:

| Return | Status |
|---|---|
| `true` | `pass` |
| `false` | `fail` |
| `'warn'` | `warn` |
| `'n/a'` | `n/a` (lazy-rendered tab not yet opened, no scan run yet, etc.) |
| throws | `error` (real bug in the predicate or upstream state) |

The runtime:

```js
window.opHealthCheck = function(tabFilter){
  var subset = tabFilter ? CHECKS.filter(c => c.tab === tabFilter) : CHECKS;
  var results = subset.map(runOne);   // {tab,label,severity,status,detail}
  console.table(results.map(r => ({Tab:r.tab,Element:r.label,Sev:r.severity,Status:r.status})));
  return results;
};
```

### 2c. UI panel

A button in a settings/diagnostics tab that calls `opHealthCheckRender('hc-result')` to render a red/amber/green HTML table inline. Lets non-console users see state.

**Severity tiers:**
- `critical` — drives a trading/mutation decision. A fail here means stop and fix.
- `important` — informs a decision but not directly actionable.
- `info` — cosmetic / contextual.

---

## 3. The `_synth` flag — propagating "this is not real"

Pattern: whenever a value comes from a non-live source, stamp `_synth: true` and `_synthSrc: <where>` on the object. Downstream code can then refuse to act on it, or render a badge.

### Producers — flag at the source

```js
function simInd(t, price){
  return {
    rsi: randRange(32, 78),
    macd: randRange(-0.8, 1.2),
    // ...
    _synth: true, _synthSrc: 'simInd'
  };
}

function simQuote(t){
  return {
    price: hardcodedBase[t] * randomMultiplier(),
    // ...
    _synth: true, _synthSrc: 'simQuote'
  };
}
```

### Scoring / enrichment — preserve, don't overwrite

When real history arrives, set `_synth` to false **only if** it wasn't already explicitly synth:

```js
if (!ind._synth) {
  ind._synth = !(hist && hist.length >= 30);
}
```

This keeps a row marked synthetic if `simInd` produced it, even if a real history fetch later happens — because the original `ind` is still a random object.

### Renderers — surface the flag

```js
'<div class="s-hdr">TECHNICAL INDICATORS'
  + (ind && ind._synth
      ? ' <span title="Values shown are placeholders..." class="synth-badge">SYNTHETIC</span>'
      : '')
+ '</div>'
```

### Safety gates — refuse to act

For any code path that mutates external state (places an order, sends a webhook, commits to a database), refuse when `_synth` is set:

```js
results.forEach(function(r){
  if (r.ind && r.ind._synth === true) { skipped++; return; }   // hard refusal
  if (!hasCredentials()) { skipped++; return; }                 // belt
  candidates.push(r);
});
if (skipped > 0) {
  log(skipped + ' signals skipped — synthetic data');
}
```

---

## 4. Defense-in-depth — multiple gates at multiple layers

Single-point gates fail when someone adds a new code path. Pattern: **gate at every layer that touches the dangerous operation.**

| Layer | Gate |
|---|---|
| Orchestrator (`runAutoScanCycle`) | Skip rows with `r.ind._synth === true`; refuse cycle when no credentials. |
| Submitter (`submitOrder`) | Refuse upfront if no credentials. Toast a clear reason. |
| Static health check | `Function.prototype.toString()` introspects each gate and verifies the guard string is still present. |

The static check is the secret weapon. Even if a future refactor accidentally strips the orchestrator gate, the static check flips red:

```js
{ tab:'api', label:'Auto-trader synth-gate present in source', sev:'critical', fn:function(){
    var src = (typeof runAutoScanCycle === 'function') ? runAutoScanCycle.toString() : '';
    if (!src) return 'n/a';
    return src.indexOf('_synth') >= 0 && src.indexOf('_autoSandbox') >= 0;
}},
```

This won't catch every regression, but it catches the most embarrassing ones — "we silently removed the safety check during a refactor."

---

## 5. Cache invariants

The pattern that keeps cache restore from re-introducing placeholders:

1. **Cache the raw object**, including any `_synth` flag.
2. **On restore**, re-run the scoring/enrichment function on every cached row. It'll re-attempt the fresh-data backfill and overwrite placeholders if history is now available.
3. **Don't trust cached values blindly.** A cache hit + a re-score is usually still cheaper than a fresh API call.

Concrete shape:

```js
var cached = JSON.parse(localStorage.getItem('cache:results') || '[]');
cached.forEach(function(r){
  if (!r || !r.id) return;
  if (!r.ind) r.ind = {};
  try {
    var sc = scoreIt(r.id, r.ind, r.opt || {});   // re-backfills from G_HIST_CACHE / loadHistCache
    if (sc) { r.score = sc.score; r.isGo = sc.isGo; /* ... */ }
  } catch(_){}
});
```

Also: **don't grow the cache without measuring serialized size against the quota** (5 MB Safari, 10 MB Chrome). One slim-cap (top 200 by score) + a quota-catch + an auto-purge of older caches is enough.

---

## 6. Lazy-render `n/a` pattern

Many apps lazy-render tab contents (rendered first time the tab is opened). Health-check predicates should return `n/a` for elements that don't exist yet, not `fail`.

Two variants:

```js
// (a) state-flag variant — tab has its own loaded flag
{ tab:'ind', label:'Industry table has rows', sev:'important', fn:function(){
    if (!(window.IND && IND.loaded)) return 'n/a';
    var t = document.getElementById('ind-body'); if(!t) return 'n/a';
    return t.querySelectorAll('tr[data-theme]').length >= 5;
}},

// (b) empty-content variant — element exists but textContent is blank
{ tab:'sc', label:'Category strip rendered', sev:'info', fn:function(){
    var el = document.getElementById('sc-cat-strip-ts');
    if (!el) return 'n/a';
    var s = (el.textContent || '').trim();
    if (!s) return 'n/a';  // lazy state, not a failure
    return true;
}},
```

Rule of thumb: **`fail` means broken. `n/a` means not-yet-rendered-or-applicable.** If you can't tell the difference, return `n/a` and add a state flag.

---

## 7. CI parse-check for single-file HTML+JS apps

Single-page apps with all JS embedded in one HTML file have a vicious failure mode: an unbalanced brace inside one `<script>` block silently halts JS execution. The page loads. The CSS renders. The buttons do nothing.

10-line workflow that catches it:

```yaml
# .github/workflows/parse-check.yml
name: Parse Check
on:
  push:    { branches: [main], paths: [index.html, '.github/workflows/parse-check.yml'] }
  pull_request: { branches: [main], paths: [index.html, '.github/workflows/parse-check.yml'] }
  workflow_dispatch:
jobs:
  parse:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - name: Validate every <script> block
        run: |
          node -e "
            const fs = require('fs');
            const html = fs.readFileSync('index.html','utf8');
            const blocks = html.match(/<script\b[^>]*>([\s\S]*?)<\/script>/g) || [];
            let errors = 0, idx = 0;
            for (const block of blocks) {
              idx++;
              const body = block.replace(/^<script\b[^>]*>/,'').replace(/<\/script>$/,'');
              if (!body.trim()) continue;
              try { new Function(body); }
              catch (e) {
                errors++;
                console.log('::error::block #' + idx + ' parse error: ' + e.message.split('\n')[0]);
              }
            }
            process.exit(errors === 0 ? 0 : 1);
          "
```

Runs in ~3 seconds. Same script works as a local sanity check before commit.

---

## 8. The handoff file (`CLAUDE.md`)

Every project should have a `CLAUDE.md` (or `AGENTS.md` / `README.dev.md`) at root that captures:

1. **Repo layout** — one line per directory.
2. **Branch convention** — `claude/<slug>` off main, squash-merge, etc.
3. **How to run checks** — exact commands for the parse-check, the health check, any tests.
4. **Architecture facts that matter** — the non-obvious invariants (in our case: scoring pipeline, indicator backfills, sector PF lookup, slim-cache, sandbox banner wiring).
5. **Recent-PR ledger** — last ~10 PRs as a table: number, subject, why. So a new session has 30 seconds of history.
6. **Known-bug list, ranked** — what's still broken, ordered by severity. Top of queue.
7. **Things to NOT do** — load-bearing footguns: "don't strip the synth gate", "don't grow the cache without measuring", "don't change KEY without updating MAP".
8. **Style notes** — "user wants terse summaries", "merge without asking", "severity tiers".

A new Claude session that reads CLAUDE.md first is 10× more useful from the first message.

---

## 9. Branch + PR workflow that scales

The flow that worked across 10 PRs in one session:

1. **One branch per concern.** `claude/healthcheck`, `claude/synth-flag`, `claude/ci-parse-check`. Easy to revert one without losing others.
2. **Non-draft PRs by default.** Drafts add friction. Open ready-to-merge.
3. **Squash-merge.** One feature = one commit on `main`. Clean history.
4. **Standing approval to merge.** Once the user says "continue without asking", honor it. Don't pause to ask "should I merge?" — that's noise.
5. **CI parse-check + PR description template.** Each PR body has: Summary (what + why), Changes table (surface → what), Test plan (checklist).

Result: ~10 PRs landed in one session, every one with a clean diff and a real test plan.

---

## 10. Common pitfalls (specific lessons)

1. **Fixing the source isn't enough if the cache is poisoned.** Scoring fix landed → page reload still showed old values. The slim-cache was caching the *current* `ind` object, including pre-fix placeholders. Fix: re-run the scoring function on every cached row at restore.

2. **Multiple fallback paths = multiple placeholder shapes.** Bulk-init used one set (`price * 0.99`), `simInd` used another (random 0.97-1.03 ratio). Each needs its own `_synth` stamp.

3. **Synthetic + auto-anything = catastrophic.** Random RSI values will occasionally pass a "RSI between 40-70" filter. If auto-trader doesn't check `_synth`, it submits real money trades on coincidence-passes. Always gate auto-mutate paths on `_synth`.

4. **Lazy DOM is not failure.** `getElementById('ind-table')` returning null could mean "broken" or "tab not yet opened." Don't conflate.

5. **The health check IS the test suite.** Don't write unit tests for "is this number > 0" — write a health-check predicate. It runs in the actual app state, against the actual DOM, and the user can run it.

6. **Static-source introspection catches refactor regressions.** A check that says "the function source still contains the string `_synth`" is dumb but bulletproof.

7. **Severity tiers matter.** Without them, a 50-fail health check looks worse than a 5-critical-fail one. Tier everything.

8. **Inventory before predicate.** Don't write checks bottom-up. Inventory every visible element across every tab first; then write predicates for the high-value ones; then expand.

---

## 11. Starter prompt for a new session on a similar project

```
The codebase is <X>. Goal: prove every visible UI element is dynamic and
live, not placeholder/stale/synthetic. Read DATA_LIVENESS_KNOWLEDGE_BASE.md
first if present — it has the patterns.

Workflow (each as its own PR):

1. INVENTORY — dispatch parallel Explore agents, one per tab/area, to
   build a table of (Element, DOM selector, JS setter, Data source,
   Pass-fail predicate). Output: HEALTHCHECK.md.

2. RUNTIME — add window.opHealthCheck() function: a CHECKS array of
   {tab,label,sev,fn}, each fn returning true/false/'warn'/'n/a' or
   throwing. Call it from the console, return + console.table the array.

3. UI PANEL — add a "DATA HEALTH CHECK" card in the diagnostics tab with
   a button calling opHealthCheckRender('hc-result'). Render results as
   a red/amber/green HTML table.

4. _SYNTH PROPAGATION — find every sim* / fallback function. Stamp
   {_synth:true, _synthSrc:<source>} on each return. Make scoreIt
   preserve an existing _synth. Surface a SYNTHETIC badge in any
   detail/preview pane that renders these objects.

5. SAFETY GATES — find every code path that mutates external state
   (orders, webhooks, DB writes). Refuse when r.ind._synth === true.
   Refuse when credentials absent. Add a static-introspection
   health-check predicate that verifies the gate's source still
   contains the guard string.

6. CI PARSE-CHECK — .github/workflows/parse-check.yml that runs
   new Function(body) over every <script> block in index.html and
   exits non-zero on any parse error.

7. CLAUDE.md HANDOFF — write the architecture facts, recent-PR
   ledger, ranked known-bug list, and things-to-not-do.

Branch convention: claude/<short-slug> off main. Non-draft PRs.
Squash-merge. User has standing approval — don't ask before merging.
Update CLAUDE.md's PR ledger row with each shipped PR.

Use a todo list for any work that's 3+ steps. Mark items complete
immediately, don't batch.
```

---

## 12. Reference — the patterns as code snippets

### Check-registry skeleton

```js
(function(){
  function $(id){ return document.getElementById(id); }
  function txt(el){ return el ? String(el.textContent||'').trim() : ''; }

  var CHECKS = [
    // {tab, label, sev: 'critical'|'important'|'info', fn: ()=> true|false|'warn'|'n/a' }
  ];

  function runOne(c){
    var observed, status, detail;
    try {
      observed = c.fn();
      status = (observed === true) ? 'pass'
             : (observed === false) ? 'fail'
             : (observed === 'warn') ? 'warn'
             : (observed === 'n/a') ? 'n/a'
             : 'pass';
      detail = typeof observed === 'number' ? observed.toFixed(2)
             : observed === true ? '✓'
             : observed === false ? '✗'
             : String(observed);
    } catch(e){
      status = 'error';
      detail = (e && e.message) || String(e);
    }
    return { tab:c.tab, label:c.label, severity:c.sev, status:status, detail:detail };
  }

  window.opHealthCheck = function(tabFilter){
    var subset = tabFilter ? CHECKS.filter(function(c){return c.tab === tabFilter;}) : CHECKS;
    var results = subset.map(runOne);
    try { console.table(results.map(function(r){
      return { Tab:r.tab, Element:r.label, Sev:r.severity, Status:r.status };
    })); } catch(_){}
    return results;
  };

  window.opHealthCheckRender = function(target){
    var el = (typeof target === 'string') ? $(target) : target;
    if(!el) return;
    var results = window.opHealthCheck();
    // ... build HTML table from results, set el.innerHTML
  };
})();
```

### Static-source health-check predicate

```js
{ tab:'safety', label:'Submit path retains synth gate', sev:'critical', fn:function(){
    try {
      var src = (typeof submitOrder === 'function') ? submitOrder.toString() : '';
      if (!src) return 'n/a';
      return src.indexOf('SANDBOX gate') >= 0 || src.indexOf('_synth') >= 0;
    } catch(_){ return 'n/a'; }
}},
```

### Three-tier history fallback

```js
function getHistory(ticker){
  if (G_HIST_CACHE[ticker]) return G_HIST_CACHE[ticker];
  var cached = loadHistCache(ticker);   // 24h TTL, min 100 bars
  if (cached) { G_HIST_CACHE[ticker] = cached; return cached; }
  return null;   // caller falls back to placeholder
}
```

### Sandbox banner toggle

```js
function _updateSandboxBanner(){
  try {
    var el = document.getElementById('hdr-sandbox');
    if(!el) return;
    var hasKey = !!_getTradierKey();   // or any "is configured" predicate
    el.style.display = hasKey ? 'none' : 'inline-block';
  } catch(_){}
}
window.addEventListener('DOMContentLoaded', _updateSandboxBanner);
// Also call after any settings save that changes credential state.
```

---

## 13. The one-sentence version

**For every visible element, you should be able to answer "where did this number come from and is the source live right now?" — and the answer should be inspectable by a button in the app.**

If you can't, build the three artifacts. If you can, keep them green.
