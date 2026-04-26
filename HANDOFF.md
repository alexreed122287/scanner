# HANDOFF BRIEFING — Option Panda Trading Scanner

> Paste this entire file as the first message in a new Claude conversation, then add your specific request after it. Claude will have full context.

## What this is

Personal trading scanner ("Option Panda") for long-calls-only swing trading. Single-file vanilla-JS app at `/Users/alex/rrjcar-Terminal-v3/index.html` (~17,500 lines), deployed to GitHub Pages at https://alexreed122287.github.io/scanner/. Backed by:

- Cloudflare Workers for Tradier + Adanos API proxying (server-side keys, never in browser)
- Python pipeline (`industry/score_themes.py`) for nightly sector RS scoring via GH Actions cron
- React sentiment panel (separate repo, embedded as sandboxed iframe)

User: solo developer/trader. Live Tradier account `6YB55403`. Mode: live. Strategy: long calls only, ~25–50 DTE, ~0.70 delta, swing horizon (days to weeks).

## Architecture quick map

```
/Users/alex/rrjcar-Terminal-v3/
  index.html                           # The scanner app (single file)
  worker/tradier-proxy/
    src/index.js                       # Tradier proxy — origin/path/token gates, body cap
    wrangler.toml                      # ALLOWED_ORIGINS env var
  industry/
    build_master_list.py               # CURATED_THEMES → master_tickers.json
    score_themes.py                    # nightly RS scoring → theme_scores.json
    master_tickers.json                # ticker-to-theme assignments
    theme_scores.json                  # daily theme composite scores (cron output)
  alex_tickers.csv                     # curated ticker universe (~2,500 syms)
  .github/workflows/score_themes.yml   # Mon–Fri 22:00 UTC cron

/Users/alex/Downloads/sentiment-panel/  # Separate repo
  src/MarketSentimentPanel.jsx         # Adanos sentiment iframe (postMessage theme sync)
  worker/src/index.js                  # Adanos proxy — null origin allowed for sandbox
```

## Deployed infrastructure

| Service | URL | Auth |
|---|---|---|
| Scanner (GH Pages) | https://alexreed122287.github.io/scanner/ | none |
| Sentiment panel (GH Pages, sandboxed iframe) | https://alexreed122287.github.io/sentiment-panel/ | none |
| Tradier proxy (Cloudflare Worker) | https://tradier-proxy.alexander-s-reed.workers.dev | `X-Live-Token` + `X-Trade-Token` |
| Adanos proxy (Cloudflare Worker) | https://adanos-proxy.alexander-s-reed.workers.dev | origin allowlist |

Cloudflare Worker secrets configured (DO NOT echo values, just know they exist):

- Tradier proxy: `TRADIER_LIVE_TOKEN`, `TRADIER_SANDBOX_TOKEN`, `LIVE_MODE_TOKEN`, `WRITE_AUTH_TOKEN`
- Adanos proxy: `ADANOS_KEY`

`localStorage` keys the scanner uses (per-device):

- `rrjcar_tradier_proxy` — workers.dev URL
- `rrjcar_tradier_proxy_live_token` — matches `LIVE_MODE_TOKEN` secret
- `rrjcar_acct` / `rrjcar_acct_live` — `6YB55403`
- `rrjcar_mode` — `live`
- `rrjcar_theme` — `light` or `dark`
- `rrjcar_smart_exits_v1`, `rrjcar_gex_schedule_v1`, `rrjcar_scan_settings_v1`, `rrjcar_notif_cooldowns_v1`, etc.

`window._tradeToken` — held in JS memory only, NEVER persisted. Re-prompted each session via the TRADE badge.

## Key features shipped (not exhaustive)

- 19-rule scoring with multi-key tiebreaker (score → tech → relStr5d → theme → volume)
- Intraday theme RS computation (catches sector rotations same-day)
- Live "TOP THEMES NOW" leaderboard strip
- GEX/FLOW tab with auto-schedule (3x/day at 9:35 / 12:00 / 15:00 ET)
- Smart Exits (intraday emergency + EOD ATR + EOD EMA cross)
- Performance analytics tab (Kelly + per-rule edge delta + IV/HV bucket P&L)
- Two-tier auth: `X-Live-Token` (reads) + `X-Trade-Token` (writes, memory-only)
- Long-calls-only optimizations (purged put logic, bullish-bias scoring)
- Auto-route to order ticket DISABLED (user explicitly opted out)

## User preferences / decisions made

- **Long calls only** — never trades puts. Scoring weighted bullish.
- **No auto-routing to order ticket** — alerts OK, hijacking NOT OK
- 15-min auto-scan recommended during market hours (not yet enabled)
- GEX 3x/day schedule — enabled
- Hidden tabs: BUY SIGNALS, OPTIONS WATCHLIST (DOM preserved, just hidden buttons)
- Default scan tab: FULL SCANNER
- No earnings filter default: 1 day
- TradingView integration declined — chart embed not wanted
- Style: ship surgically, validate JS via `node -e "..."` before commit, comment fixes thoroughly

## Pending action items

### 🟡 Important (batch when convenient)

| ID | What | Effort |
|---|---|---|
| F-3 | Cron will silently auto-disable after 60d inactivity. Add failure-notification step (open GH issue or Slack on N consecutive failures). | 15 min |
| F-5 | `resetScanSettings` doesn't clear OB filter checkboxes + doesn't reset sector multi-select | 5 min |
| F-6 | `loadScanSettings` masks new HTML defaults silently — no version field on snapshot. Bump key to `_v2` or store defaults-version | 5 min |
| F-8 | `_ensureIntradayThemeRS` memoization poison if called before `G.results` populated. Don't update gen counter when bailing on empty results | 5 min |

### 🟢 Quick wins

- **F-9**: SPY-missing FATAL message in pipeline doesn't mention solo-retry was attempted
- **F-10**: yfinance per-chunk failures aren't separately counted from "got partial"
- **F-11**: `getThemeStrengthLive` could add `&& rsMap[ti.theme] != null` for paranoia

### ✅ Recently shipped

- **F-1** (GEX schedule double-fire) — range debounce instead of equality
- **F-2** (high-conviction alert spam on reload) — `G_NOTIF_COOLDOWNS` persisted to `localStorage` with 24h TTL
- **F-7** (portfolio Promise.all partial failure) — positions wrapped in sentinel-returning catch so cash still renders
- **F-4** (Data Center tickers in `alex_tickers.csv`) — verified APLD, NBIS, CRWV, IREN, WULF, CIFR all present

## How to verify state in a fresh session

Paste in browser console:

```js
console.log({
  mode: localStorage.getItem('rrjcar_mode'),
  proxyUrl: localStorage.getItem('rrjcar_tradier_proxy'),
  hasLiveToken: !!localStorage.getItem('rrjcar_tradier_proxy_live_token'),
  acct: localStorage.getItem('rrjcar_acct'),
  results: G.results?.length,
  themesInOverlay: Object.keys(G_THEME_OVERLAY?.ticker2theme || {}).length,
  gexTickers: G.gexData?.length,
  gexSchedule: G.gexAutoSchedule
});
```

Should show: `mode: live`, `proxyUrl` set, `hasLiveToken: true`, `acct: 6YB55403`, themes mapped (~2000+), GEX schedule preference.

## Quick commands

```bash
# Verify worker gates from terminal
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "Origin: https://alexreed122287.github.io" \
  -H "X-Live-Token: <LIVE_TOKEN>" \
  "https://tradier-proxy.alexander-s-reed.workers.dev/v1/user/profile?mode=live"
# Expected: 200

# Check today's deployed theme scores
curl -s "https://alexreed122287.github.io/scanner/industry/theme_scores.json?cb=$(date +%s)" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('as_of:', d.get('as_of'), '| themes:', len(d.get('themes',{})))"

# Manually trigger pipeline cron (when needed)
gh workflow run score_themes.yml --repo alexreed122287/scanner

# Validate scanner JS doesn't have syntax errors
node -e "const fs=require('fs'); const html=fs.readFileSync('/Users/alex/rrjcar-Terminal-v3/index.html','utf8'); const re=/<script>([\s\S]*?)<\/script>/g; let m,idx=0,fails=0; while((m=re.exec(html))!==null){idx++; try{new Function(m[1])}catch(e){fails++; console.log('FAIL:',e.message.slice(0,150))}} console.log(idx+' blocks, '+fails+' fails');"
```

## Recent session-end commits (most recent first)

- `a78a025` feat(portfolio): show Tradier account ID + include cash in totals
- `d38c25a` fix(portfolio): pfAutoPullTradier auto-discovers account
- `5889255` feat: 5-item batch — disable auto-route, change defaults, save/reset, Data Center
- `c5cb098` fix(scanner): high-conviction check waits for enrichment to finalize
- `f0a56cc` + `5001338` feat(scanner): live theme leaderboard strip
- `e10ffbc` feat(scanner): intraday theme RS — Strong Sector responds same-day
- `8bdff29` fix(scanner): skip GEX post-scan auto-trigger when GEX is <30min fresh
- `e37b7d9` feat(scanner): GEX auto-schedule + cache persistence + header layout fix
- `8b2378d` fix(scanner): add GEX/FLOW tab — was missing entirely
- `d350275` fix(industry): yfinance rate-limit hardening
- `f9cb639` fix(ci): drop pip cache from score_themes workflow

## Notes on what's NOT included

- **Worker secret values** — never echoed. The names are listed so a new session knows they exist; if you need to reset/rotate, walk through `wrangler secret put` interactively.
- **Trade token raw value** — same reason. `window._tradeToken` is memory-only; the user re-arms it via the TRADE badge each session.
- **Conversation chatter** — only durable decisions made it in. A new session doesn't need to relive every back-and-forth.
