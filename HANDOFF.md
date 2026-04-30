# HANDOFF BRIEFING — Option Panda Trading Scanner

> Paste this entire file as the first message in a new Claude conversation (incl. Claude Dispatch on mobile), then add your specific request after it. Claude will have full context.

## What this is

Personal trading scanner ("Option Panda") for long-calls-only swing trading. Single-file vanilla-JS app at `/Users/alex/rrjcar-Terminal-v3/index.html` (~21,200 lines), deployed to GitHub Pages at https://alexreed122287.github.io/scanner/. Backed by:

- Cloudflare Worker for Tradier API proxying (server-side keys, X-Live-Token + X-Trade-Token gates)
- Python pipeline (`industry/score_themes.py`) for nightly sector RS scoring via GH Actions cron — Tradier-backed since 2026-04-29
- Sentiment subsystem **fully removed 2026-04-29** (tab, header chips, iframe, JS module, CSS — all gone)

User: solo developer/trader. Live Tradier account `6YB72268`. Mode: `live`.

**Strategy on paper:** long calls only, ~25-50 DTE, ~0.70 delta, swing horizon (days to weeks).
**Strategy in practice (2026-04-29 council backtest of n=19 trades):** drift into ~17-23 DTE, far-OTM penny calls. 26% win rate. One outlier (POET 12.5C +$1,225 on 8-DTE) carried all P&L. Real edge unproven.

## Architecture

```
/Users/alex/rrjcar-Terminal-v3/
  index.html                           # Scanner app (single file ~21k lines)
  worker/tradier-proxy/
    src/index.js                       # Tradier proxy — origin/path/token gates,
                                       #   /circuit-breaker/snapshot endpoint,
                                       #   115/min rate limit, multileg-aware
    wrangler.toml                      # KV ns 168aef8dca8444cfbc96d989d09b5cca
                                       #   (cross-device sync + circuit breaker state)
  industry/
    score_themes.py                    # nightly RS scoring, Tradier-primary +
                                       #   yfinance fallback. fetch_prices() at line 248.
    master_tickers.json                # ticker-to-theme assignments
    theme_scores.json                  # daily theme composite scores (cron output)
  alex_tickers.csv                     # ~2,500 ticker universe
  .github/workflows/score_themes.yml   # Mon–Fri 22:00 UTC cron
```

## Deployed infrastructure

| Service | URL | Auth |
|---|---|---|
| Scanner | https://alexreed122287.github.io/scanner/ | none |
| Tradier proxy | https://tradier-proxy.alexander-s-reed.workers.dev | X-Live-Token + X-Trade-Token |

**Worker secrets** (managed via `wrangler secret put`):

- `TRADIER_LIVE_TOKEN` — production Tradier API key
- `TRADIER_SANDBOX_TOKEN` — sandbox (optional)
- `LIVE_MODE_TOKEN` — X-Live-Token gate value
- `WRITE_AUTH_TOKEN` — X-Trade-Token gate value (**may not be set as of 2026-04-29 evening** — check with `wrangler secret list`. If absent, write gate is bypassed.)

**KV namespace `SYNC_CONFIG`** (id `168aef8dca8444cfbc96d989d09b5cca`):
- `__circuit_breaker__` — daily/weekly drawdown state (engaged only if user manually posts via `postCircuitBreakerSnapshot()`)
- `<masterSecretHash>` — encrypted settings sync blobs (Option C cross-device sync)

**GitHub Actions secret `TRADIER_TOKEN`** (set 2026-04-29) — same value as worker's `TRADIER_LIVE_TOKEN`. Used by `score_themes.py` cron to fetch via Tradier instead of yfinance (Yahoo rate-limits CI IPs).

## `localStorage` keys (per-device, NOT in cloud sync until pushed)

**Settings:**
- `rrjcar_tradier_proxy` = `https://tradier-proxy.alexander-s-reed.workers.dev`
- `rrjcar_tradier_proxy_live_token` = matches `LIVE_MODE_TOKEN` worker secret
- `rrjcar_acct` / `rrjcar_acct_live` = `6YB72268`
- `rrjcar_mode` = `live`
- `rrjcar_fmp` = FMP API key (Starter plan: 300/min, ~75k/day)
- `rrjcar_scan_settings_v2` = saved Min Score + filter state
- `rrjcar_smart_exits_v1`, `rrjcar_gex_schedule_v1`, `rrjcar_notif_settings_v1`
- `rrjcar_pnl_baseline` = bankroll baseline ($)

**Caches (auto-managed):**
- `rrjcar_hist_<TICKER>` — daily-bar history cache, 24h TTL, 100-entry cap. **Rejects entries <100 bars** (post-2026-04-29 — enforces 400-day fetch).
- `op_cache_scan_results` + `_ts` — slim scan result cache for fast reload
- `op_cache_closed` — closed-trades reconciliation
- `rrjcar_shadow_book_v1` — auto-logged contract picks for IC analysis
- `rrjcar_shadow_scan_v1` — per-rule pass/fail per scanned ticker per day (council #5)
- `rrjcar_tilt_log_<DATE>` + `rrjcar_tilt_log_all` — EOD reconciliation journal

`window._tradeToken` — held in JS memory only, NEVER persisted. Re-prompted each session via the TRADE: locked badge.

## Scoring rules (current state, after 2026-04-29 council overhaul)

**Section A — Technical Momentum** (Tradier quote-derived, no history needed):
- RSI 40-70 (+6) + RSI 50-65 Cardwell zone (+6 bonus)
- MACD Hist > 0 (+10)
- ADX > 25 (+6) + ADX 15-25 + DI+>DI- (+6 bonus, only fires on detail-load)
- EMA20 > EMA50 (+10)
- TF Aligned 2/3 (+12)
- Sector PF > 2 (+5)
- 52wk Hi <15% (+8) + 52wk Hi <5% George-Hwang bonus (+6)
- RS > SPY 21d if available else 5d (+10)
- Price > EMA200 (+6)

**Section B — FMP** (analyst data):
- Analyst Revisions ↑ (+16)
- Analyst PT exists (+8)

**Section D — Momentum** (history-based):
- MFI(14) > 50 (+10)
- CMO(9) > 50 (+7)

**NEW Evidence-based rules** (require 400-day history):
- Minervini Trend Template (+15) — 6 criteria
- Pocket Pivot (+15) — O'Neil/Morales-Kacher
- U/D Volume Ratio 50d tiered (+12 / +8 / +4)
- VCP — ATR Contraction (+12)
- BBW Squeeze <p20 of 120d (+10)
- 20d Donchian Breakout + 1.5× vol (+12)
- JT 12-1 Momentum top quintile proxy (+15)

**GEX Flow** (with extreme-positioning penalty):
- ≥75% calls = **−6** (overcrowded contrarian)
- 70-74% = +6
- 55-69% = +4

**Other:** Strong Sector ±8, AVOID -15, PROVEN +8, Broken Trend penalty.

**Default GO threshold:** 150 (≈ 60% of new ~252-pt max).

## State as of 2026-04-29 evening

24+ commits today. Recent sequence:

1. Council overhaul: 3-anti-signal drops + parameter retunes + 7 new evidence-based rules
2. GO threshold default 100→150
3. History fetch 25→400 days (required for new rules)
4. Background enrichment (top 60 foreground + 61-200 background, 30/min)
5. Worker rate 100→115/min, SC_ENRICH_LIMIT 200→60
6. **All operator-protective blockers REMOVED per user instruction** — only loop detector retained
7. Mobile horizontal-bleed fix
8. Sentiment subsystem fully removed
9. Multiple recovery rounds (Safari wiped localStorage; rotated tokens, restored 5 critical keys)

**Open items:**

| Item | Status |
|---|---|
| Cron run `25141222712` | In progress as of session end. Tradier-backed (~42 min total expected). Check: `gh run list --workflow=score_themes.yml --limit=1 -R alexreed122287/scanner` |
| `WRITE_AUTH_TOKEN` worker secret | May be unset. Verify: `wrangler secret list`. If missing: `openssl rand -hex 16 \| npx wrangler secret put WRITE_AUTH_TOKEN; npx wrangler deploy` then set same value in browser via TRADE badge. |
| Cloud sync push | Should push to lock in recovery: API tab → SYNC card → master secret → PUSH TO CLOUD |

## Phone-specific limitations (Claude Dispatch)

You can't run Terminal/CLI commands from phone. So:

❌ `npx wrangler` (worker secrets / deploys)
❌ `gh` CLI commands
❌ Local filesystem edits to `index.html`
❌ Local git operations
❌ Manual `curl` debugging

**What you CAN do via phone:**

✅ Read code from GitHub via raw.githubusercontent.com URLs (WebFetch)
✅ Hit the worker directly with `fetch()` calls in scanner browser console
✅ Triage GitHub Actions runs via github.com URLs (WebFetch)
✅ Discuss strategy / architecture / next steps
✅ Draft code changes for later application from desktop
✅ Inspect localStorage state via browser console
✅ Manually scan, click into tickers, place orders

## Notable session insights

- **Council ran 4 times today** with domain-specialized advisors (Quant, Risk, Microstructure, Behavioral, Engineering)
  - Operator >> tooling problem (18 of 19 trades violated stated rules)
  - 5d RS, %chg accel, RSI(7) accel = anti-signals or noise → dropped
  - Stated 25-50 DTE strategy != actual 17-23 DTE drift
  - **Behavioral advisor's standing recommendation: 2-week full stop** on trading + dashboard commits to test whether the impulse is discretionary or compulsive. User declined; removed all blockers instead.

- **Deferred council picks (research-backed, ready to ship next):**
  - IV bid-ask spread quality gate (~4 hr)
  - Yang-Zhang HV upgrade (~30 LOC)
  - OBV/Price divergence
  - Weinstein Stage 2A initiation
  - MACD zero-line cross + histogram-rising
  - EMA 8/21/55 swing variant
  - py_vollib via GH Actions cron for IV surface
  - vectorbt backtest of last 90 days
  - VIX term-structure ribbon (regime gauge)

## Recent commits (most recent first)

- `2a2b3b9` — remove sentiment tab + all related code
- `0b41cd5` — feat: background enrichment + cache-quota fix
- `f2f97d8` — fix(scoring): tame the rate-limit storm
- `0d8e388` — fix(scoring): bump history fetch 25d→400d
- `d316b26` — fix(scoreIt): guard diPlus/diMinus access
- `ade0452` — fix(shadow-scan): batch write
- `b7e5272` — scoring (3/3): add 7 evidence-based swing-entry rules + GO threshold 150
- `af3db6f` — scoring (2/3): retune existing rules to evidence-based parameters
- `d7856fc` — scoring (1/3): drop 3 anti-signals
- `e63f434` — trading: remove blockers per user direction
- `736855c` — council: ship all 10 recommendations
- `693612e` — council-driven: hard-block gate + shadow book + intraday signals + multileg defense
- `647b057` — streaming: WebSocket quotes for active order ticket
- `28e165c` — trading: atomic multileg roll + slippage capture + tag legs + unified score
- `debfc1e` — trading-logic: contract filter + walker anchor + pre-trade gate + matrix CSV

For full log: `git log --oneline -50` from `/Users/alex/rrjcar-Terminal-v3/`

## Key project memory files

Auto-loaded by Claude from `~/.claude/projects/-Users-alex/memory/`:

- `project_option_panda.md` — top-level project memory (live Tradier acct 6YB72268, this dashboard)
- `feedback_pinescript_*.md`, `project_mirofish.md`, `project_options_dashboard_presets.md` — adjacent projects

## How to resume on phone via Claude Dispatch

1. Open https://alexreed122287.github.io/scanner/ in mobile Safari
2. Open Claude Dispatch on phone
3. Either paste this entire HANDOFF.md as your first message, OR tell Claude:
   ```
   Read https://raw.githubusercontent.com/alexreed122287/scanner/main/HANDOFF.md
   ```
4. Then state your request. Claude will have full project context.

---

**Last updated:** 2026-04-29 evening — post-sentiment-removal, cron run `25141222712` in progress, all operator blockers removed per user, scoring overhaul live with default GO=150 against ~252-pt max.
