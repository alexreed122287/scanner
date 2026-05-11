# Option Panda — Dashboard Overview

A single shareable reference for the **Option Panda** trading dashboard at
<https://alexreed122287.github.io/scanner/>. Covers the user-facing
layout, the design system, the persisted configuration, and the
build/deploy flow.

Audiences: end-users trying to make sense of the UI, developers
forking or extending the code, and designers reviewing the visual spec.

---

## 1. At a glance

| | |
|---|---|
| **Name** | Option Panda |
| **What it is** | Single-page options-trading scanner + order terminal — long-call swing-trade workflow |
| **Tech** | Vanilla HTML/CSS/JS in one `index.html` (~31k lines), served as a static site by GitHub Pages |
| **Backend** | Cloudflare Worker proxy in front of the Tradier brokerage API; nightly Python cron computes sector/theme relative strength |
| **Install** | PWA — installable on iPhone/Android home screen via `manifest.json`; works offline-ish via `sw.js` |
| **Live site** | <https://alexreed122287.github.io/scanner/> |
| **Repo** | <https://github.com/alexreed122287/scanner> |

---

## 2. Layout anatomy

The viewport is locked to `100dvh` and `overflow:hidden` on `<body>` —
no page-level scroll. Each tab pane owns its own scroll surface. There
are four fixed pieces of chrome stacked top-to-bottom:

```
┌────────────────────────────────────────────────┐
│  #hdr        — logo · clock · indices · chips │  fixed-height
├────────────────────────────────────────────────┤
│  #nav        — top tab strip (desktop only)   │  fixed-height
├────────────────────────────────────────────────┤
│                                                │
│  #app  →  .tab-pane.active                    │  flex:1, internal scroll
│                                                │
├────────────────────────────────────────────────┤
│  #bot-nav    — bottom tab-bar (mobile only)   │  fixed, overlays home indicator
└────────────────────────────────────────────────┘
```

### Header (`#hdr`)
- **Logo + brand** (`OPTION PANDA`) with a panda icon. Double-tap = hard
  cache refresh.
- **Inline clock** in JetBrains Mono next to the brand.
- **Version chip** (`v2.16.x`) — tap to force-reload.
- **Indices marquee** (`#hdr-tickers`) — SPY, QQQ, DIA, IWM, VIX, GLD,
  SPX. On mobile this becomes an auto-scrolling marquee (60s loop).
- **Quick chips** (`#hdr-chips`) — light/dark toggle, `TRADE: locked`
  badge (gates write actions until the session token is entered).
  Collapsed behind a `⋯` hamburger on phones.

### Top nav (`#nav`)
13 tabs in a single horizontal strip. On iPhone (`≤480px`) tabs wrap
to two rows so all are visible without swiping; on tablet/laptop
(`481–1024px`) they scroll horizontally; on desktop (`≥1025px`) they
fit on one line.

### Bottom nav (`#bot-nav`)
Mobile-only iOS-style tab bar pinned to the home-indicator area.
Surfaces the 4–5 highest-traffic tabs (Scanner, Order, Positions,
Watchlist, More).

### Tab panes (`.tab-pane`)
Only one is `.active` at a time. Each is `display:none` until selected.
The active pane is `overflow-y:auto` so its own content scrolls
independently of the rest of the chrome.

### Floating help (`.help-fab`)
A 36×36 `?` circle pinned bottom-right (above the bot-nav on mobile).
Opens a per-tab "HOW TO" modal.

---

## 3. Tabs

There are 13 tab panes total. Listed in nav order:

| ID | Label | Purpose |
|---|---|---|
| `tab-bs` | Buy Signals | (Hidden) Filtered sticky list of GO-signal tickers. |
| `tab-sc` | **FULL SCANNER** | Default landing. Runs the 19-rule scoring engine across the ~2,500-ticker universe and renders a sortable results table. Click a row → detail pane (desktop) or bottom sheet (mobile). |
| `tab-order` | Order Ticket | Place a stock or option order through the Tradier proxy. Includes preview, limit/market/step-fill, trailing-stop config, Smart Exits (ATR/EMA/HV trailing). |
| `tab-gex` | GEX / Flow | Gamma-exposure dashboard. Pulls 30-DTE option chains for the top-200 enriched tickers and computes call/put OI flow + gamma-flip strike. Drives the "GEX Call Heavy" scoring rule. |
| `tab-ind` | Industry | Theme/sector leaderboard. Renders `industry/theme_scores.json` written by the nightly cron — relative strength per theme with sparklines. |
| `tab-pos` | Positions | Live Tradier positions, per-row P&L, day P&L, trailing-stop status, roll/close actions, payoff-curve chart. |
| `tab-news` | News | General market + per-ticker headlines via the Financial Modeling Prep (FMP) API. |
| `tab-pf` | Portfolio | Multi-column portfolio builder. Paste, CSV-import, or auto-pull from Tradier; per-column charts and stats. |
| `tab-al` | Alerts | Recent high-conviction alerts log + browser notification + EmailJS config. |
| `tab-wl` | Watchlist | Hand-curated ticker watchlist with candle chart, EMA 10/20/50, S/R levels. |
| `tab-howto` | How To | First-time user walkthrough — what every tab does, API setup, reading scan results, placing trades. |
| `tab-api` | API | Save / test / clear Tradier + FMP keys, FMP cache management, live-mode token UI, balances refresh, cloud-sync config. |
| `tab-cw` | (hidden) Options Watchlist | Per-contract watchlist (separate from the ticker watchlist). |

### Scanner tab — the centerpiece

Above the results table sits a sticky 4-segment action row:

| Segment | Expands to |
|---|---|
| **STRATEGY** | Preset chips — HIGH CONVICTION, BREAKOUT, MOMENTUM, BEST ITM CALLS, PRE/POST MARKET, CLEAR. Each preset applies a curated combination of filters + min-score. |
| **FILTERS** | Sector multi-select, theme multi-select, GO/NO-GO signal, Min Score. |
| **MUST PASS** | 16 indicator chips (Analyst Revisions, GEX Call Heavy, 52Wk Hi <15%, RS > SPY, MACD+, TF Aligned 2/3, > EMA200, Vol > Avg, No Earnings, Strong Sector, JT 12-1 Mom, Minervini, Pocket Pivot, VCP, Donchian 20d, PROVEN). Toggle = hard filter. |
| **SCREENER** | Numeric inputs (price range, market cap, options price ceiling, earnings DTE, etc.). |

Right-aligned permanent controls: ↻ **SCAN**, ▲ **EXPORT GOs**, search box, last-scan timestamp, data-status pill.

Results table on **desktop** shows all columns: ★ Star, Rank/Why,
Ticker (with GEX pill), Score bar, Signal badge, ▲ BUY button, Theme,
Sector, Price, Change%, Volume, Tech, Fund, RS 5D, GEX Flow, Call%.
On **mobile** the table scrolls horizontally so every column stays
reachable via swipe (as of v2.16.19).

---

## 4. Design system

### Color tokens — dark theme (default)

| Token | Value | Used for |
|---|---|---|
| `--bg0` | `#050d14` | Page background |
| `--bg1` | `#071018` | Header, cards, table |
| `--bg2` | `#0b1522` | Stat boxes, slight elevation |
| `--bg3` | `#111b2e` | Borders, dividers, hover |
| `--amb` / `--blu` | `#00d4ff` | **Primary accent** — links, active tabs, cyan glow |
| `--ambb` / `--blub` | `#40e8ff` | Hover state of `--amb` |
| `--ngo` | `#ff00e6` | Magenta — TRADE badge, "danger zone" actions |
| `--grn` | `#22c55e` | Positive P&L, GO badge, BUY |
| `--red` | `#ef5350` | Loss-direction, NO-GO emphasis |
| `--wrn` | `#ffd740` | Amber warning, NO-GO badge |
| `--wht` | `#c8daf8` | Default body text |
| `--gry` / `--gry2` | `#7090c8` / `#3d5580` | Secondary / tertiary text |
| `--glow-cyan` | `0 0 18px rgba(0,212,255,.5)` | Active-button / SCAN-button glow |

### Color tokens — light mode

Triggered by `body.light-mode`. Uses an **Okabe-Ito-inspired colorblind-safe palette** with WCAG AA contrast on white:

| Token | Value | Notes |
|---|---|---|
| `--bg0` → `--bg3` | `#fff` → `#d9d9d9` | Greyscale steps |
| `--amb` | `#005bbb` | Blue accent (replaces cyan) |
| `--ngo` | `#cc79a7` | Mauve |
| `--grn` | `#117733` | Forest green |
| `--red` | `#cc1f1f` | Stop-sign red |
| `--wrn` | `#d55e00` | Vermillion |

Glow tokens collapse to `0 0 0 transparent` in light mode for clean
printing/sharing.

### Typography

| Family | Use |
|---|---|
| `Inter` (`--ff`) | Body, controls, table rows |
| `JetBrains Mono` (`--ff-mono`) | Tickers, prices, %s, badges, clocks, anywhere tabular alignment matters |
| `Orbitron` (`--ff-brand`) | Brand logo "OPTION PANDA" |

Body baseline is `13px / 1.5` weight 500. Tables and badges down-shift
to `10–11px` weight 600–800.

### Breakpoints

| Width | Treatment |
|---|---|
| **≤480 px** (iPhone) | Two-row tab nav, bottom tab-bar, bottom-sheet detail panels, condensed filter bar, fixed bottom action row on Order Ticket, marquee header indices, horizontal-swipe scan table. |
| **481–768 px** (Phablet) | Bottom tab-bar still on, top nav scrolls horizontally. |
| **769–1024 px** (iPad portrait) | Desktop chrome (no bottom bar), but scanner table + detail share 55/45 split instead of 65/35. |
| **≥1025 px** (Desktop) | Full chrome — header chips inline, top tabs single-line, scanner table 65% / detail 35%, all `col-hide-mobile` cells visible. |

### Iconography & affordances

- Borders use `1px solid #0e1826` via `--bdr`.
- Radii use `--rad: 6px` for cards; tighter `3px` for pills/badges.
- Sticky elements (action row, detail header) use `position:sticky; top:0` inside the tab-pane's scroll container.
- Modals layer at `z-index 7000-8500` with `backdrop-filter:blur(3px)`.
- The detail sheet on iPhone slides up from `bottom:0` with `border-radius:14px 14px 0 0` and `box-shadow:0 -8px 28px`.

---

## 5. Configuration

### Required API keys (set in the API tab)

| Service | Key | Why |
|---|---|---|
| **Tradier proxy** | URL + `X-Live-Token` | All Tradier reads/writes go through this Cloudflare Worker — never the user's browser directly. |
| **FMP** | API key (Starter plan: 300/min, ~75k/day) | Analyst revisions, price targets, earnings calendar, news. |
| **EmailJS** *(optional)* | Service ID + template ID + public key | High-conviction email alerts. |

The Tradier brokerage key itself **never** leaves the worker — it's
injected server-side from `TRADIER_LIVE_TOKEN`/`TRADIER_SANDBOX_TOKEN`
worker secrets. The browser only holds a non-brokerage "live-mode"
gate token.

A **trade token** (`X-Trade-Token`) is required for any write action
(submit order, close position, roll). Held in JS memory only —
re-prompted every session via the magenta `TRADE: locked` chip in the
header.

### Persisted settings (browser `localStorage`)

All keys are prefixed `rrjcar_*` so they're easy to grep.

**App config:**

| Key | Owns |
|---|---|
| `rrjcar_tradier_proxy` | Worker URL |
| `rrjcar_tradier_proxy_live_token` | Live-mode gate token |
| `rrjcar_acct` / `rrjcar_acct_live` | Tradier account number |
| `rrjcar_mode` | `live` / `sandbox` |
| `rrjcar_fmp` | FMP API key |
| `rrjcar_app_settings_v1` | UI prefs (theme, etc.) |
| `rrjcar_scan_settings_v2` | Saved filter state + Min Score |
| `rrjcar_smart_exits_v1` | ATR/EMA/HV exit config |
| `rrjcar_gex_schedule_v1` | `off` / `open` / `3x` GEX auto-schedule |
| `rrjcar_notif_settings_v1` | Browser/email notification prefs |
| `rrjcar_auto_scan` | Auto-rescan timer config |

**State / caches (auto-managed):**

| Key | Owns | TTL |
|---|---|---|
| `rrjcar_gex_cache_v1` | Last GEX run (call %, flip strike, OI flow) | 24h |
| `rrjcar_wl` | Ticker watchlist | persistent |
| `rrjcar_pos_open` | Per-position entry snapshot (for closed-trade attribution) | persistent |
| `rrjcar_ts_config` / `rrjcar_ts_state` | Trailing-stop config + per-symbol state | persistent |
| `rrjcar_eq_trail` | Equity-side trailing stop | persistent |
| `rrjcar_sel_sectors` | Sector multi-select state | persistent |
| `rrjcar_theme_overlay_v1` | Daily theme RS overlay (from `theme_scores.json`) | 24h |
| `rrjcar_earnings_v2` | Earnings calendar | 24h |
| `rrjcar_notif_cooldowns_v1` | Per-ticker high-conviction alert cooldowns | 24h |
| `rrjcar_hist_<TICKER>` | 400-day daily-bar history per ticker | 24h, 100-entry LRU cap |
| `rrjcar_fmp_<TICKER>` | Per-ticker FMP analyst payload | per-ticker |
| `rrjcar_closed_trades` | Reconciled buy/sell pairs for performance analytics | persistent |

`window._tradeToken` and `window._liveTokenCache` are JS-memory-only
and not in `localStorage`.

### Server-side configuration

Worker secrets are managed via `wrangler secret put` (never in source):

- `TRADIER_LIVE_TOKEN` — production brokerage key
- `TRADIER_SANDBOX_TOKEN` — sandbox brokerage key
- `LIVE_MODE_TOKEN` — must match browser's `rrjcar_tradier_proxy_live_token`
- `WRITE_AUTH_TOKEN` — must match the session's `_tradeToken`

Plus `wrangler.toml` declares `ALLOWED_ORIGINS` (browser origins that
may hit the worker) and a Workers KV namespace
(`168aef8dca8444cfbc96d989d09b5cca`) for circuit-breaker state and
end-to-end-encrypted cross-device settings sync.

A GitHub Actions secret `TRADIER_TOKEN` (same value as
`TRADIER_LIVE_TOKEN`) is used by the nightly cron so it can fetch
prices through Tradier instead of yfinance (Yahoo rate-limits CI IPs).

---

## 6. Architecture

```
┌────────────────────────────────────────────────────────────────┐
│  Browser  ──  index.html  (vanilla JS + Chart.js)              │
│                                                                │
│   ├─ Global state  →  window.G  (in-memory)                    │
│   ├─ Persistence    →  localStorage (rrjcar_*)                 │
│   └─ Charts         →  Chart.js 4.4 (CDN)                      │
└─────────────────────────┬──────────────────────────────────────┘
                          │  X-Live-Token + X-Trade-Token
                          ▼
┌────────────────────────────────────────────────────────────────┐
│  Cloudflare Worker  —  worker/tradier-proxy                    │
│    · Origin allowlist (ALLOWED_ORIGINS)                        │
│    · Path allowlist  (ALLOWED_PATH_PREFIXES, _EXACT_PATHS)     │
│    · Tradier key injected server-side                          │
│    · 115 req/min global rate limit                             │
│    · Constant-time token compare                               │
│    · /circuit-breaker/snapshot custom endpoint                 │
│    · KV-backed cross-device encrypted settings sync            │
└─────────────────────────┬──────────────────────────────────────┘
                          ▼
                 ┌─────────────────────┐
                 │   Tradier REST API  │
                 └─────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│  GitHub Actions — nightly cron (Mon–Fri 22:00 UTC)             │
│    industry/score_themes.py                                    │
│    · Tradier-primary, yfinance fallback                        │
│    · Computes theme/sector RS scores                           │
│    · Writes industry/theme_scores.json                         │
│    · Smoke-test gated (industry/test_theme_scores.py)          │
└────────────────────────────────────────────────────────────────┘
```

**No build step.** `index.html` is both source-of-truth and what
GitHub Pages serves. Edits to it deploy directly when pushed to `main`.

**Single-state-object pattern.** All in-memory state lives on a global
`G` object (declared around line 3845). This makes the app inspectable
from any browser console — `G.results`, `G.filtered`, `G.positions`,
etc. The `MAP.md` file in the repo lists every subsystem and the line
range it owns.

---

## 7. Build & deploy

| Action | How |
|---|---|
| **Run locally** | `python3 -m http.server 8000` from repo root → <http://localhost:8000/> |
| **Deploy frontend** | `git push origin main` — GitHub Pages picks it up in ~60s |
| **Cache-bust on clients** | The `<meta name="op-build">` tag + `APP_VERSION` constant get bumped per release; double-tap the panda icon or version chip to force-reload + clear service worker cache |
| **Deploy worker** | `cd worker/tradier-proxy && npx wrangler deploy` |
| **Rotate worker secret** | `openssl rand -hex 16 \| npx wrangler secret put <NAME>` then `wrangler deploy` |
| **Run nightly cron manually** | `gh workflow run score_themes.yml -R alexreed122287/scanner` |
| **Lint / static analysis** | Auto on every PR — `.github/workflows/static-analysis.yml` runs ESLint (security plugin) + Semgrep (OWASP + JS) |

PR review of the static-analysis checks is the only deploy gate. There
are no unit tests for the JS — testing is browser-first, in-prod via
sandbox mode.

---

## 8. Repo layout

```
scanner/
├── index.html                      Scanner app (~31k lines, source of truth)
├── manifest.json                   PWA manifest
├── sw.js                           Service worker (offline-ish)
├── OneSignalSDKWorker.js           (Stub) push provider
├── apple-touch-icon.png            iOS home-screen icon
├── icon-180/192/512.png            PWA icons
├── favicon.ico                     Browser tab icon
├── assets/                         Splash video, panda icon, etc.
│
├── worker/tradier-proxy/           Cloudflare Worker
│   ├── src/index.js                · Origin/path/token gates, rate limit
│   ├── wrangler.toml               · KV namespace, ALLOWED_ORIGINS
│   └── README.md
│
├── industry/                       Nightly RS-scoring pipeline
│   ├── score_themes.py             · Cron: fetch prices, compute RS
│   ├── build_master_list.py        · Build ticker→theme mappings
│   ├── audit_unassigned.py         · Heuristic theme-assignment
│   ├── test_theme_scores.py        · Pytest smoke test (deploy gate)
│   ├── master_tickers.json         · Generated: ticker → theme
│   ├── theme_scores.json           · Generated: daily theme RS (live)
│   └── theme_scores_history.json   · Generated: historical scores
│
├── alex_tickers.csv                Curated ~2,500 ticker universe
├── tickers/                        Per-ticker data
├── gex/                            GEX snapshots
│
├── tools/audit/                    Static-analysis configs
│   ├── eslint.config.mjs           · ESLint security plugin
│   ├── extract-scripts.js          · Pulls <script> blocks out for linting
│   └── fuzz-tradier-proxy.sh       · Read-only worker fuzz
│
├── .github/workflows/
│   ├── score_themes.yml            · Mon–Fri 22:00 UTC cron
│   └── static-analysis.yml         · ESLint + Semgrep on push/PR
│
├── DASHBOARD.md                    ← this file
├── MAP.md                          Code map — subsystem table + function index
├── HANDOFF.md                      New-session briefing (paste into Claude on phone)
├── TICKERS_FULL.md                 Full ticker universe doc
└── README.md                       (empty placeholder)
```

---

## 9. Glossary

| Term | Meaning |
|---|---|
| **GO / NO-GO** | Binary classification output by `scoreIt`. GO = score ≥ Min Score (default 130 in UI, 150 historical). |
| **HIGH CONVICTION** | Strategy preset: PROVEN + Score ≥140 + Analyst Revisions ↑ + GEX Call Heavy + JT 12-1 Mom + Minervini Trend Template. |
| **GEX** | Gamma exposure — dealer-hedging pressure derived from 30-DTE option chain open interest. "Call Heavy" = ≥55% of OI on calls. |
| **JT 12-1 Mom** | Jegadeesh-Titman cross-sectional momentum, top quintile proxy (returns over last 12 months excluding the most recent). |
| **Minervini Trend Template** | 6-criteria O'Neil/Minervini trend filter (above MA50/150/200, MA stack order, distance from 52-wk high/low). |
| **VCP** | Volatility Contraction Pattern — ATR contraction over the prior base. |
| **Pocket Pivot** | O'Neil / Morales-Kacher pre-breakout volume signal. |
| **TF Aligned** | "Time-Frame Aligned" — count of trend timeframes (daily / hourly / 15-min) pointing the same direction. |
| **PROVEN** | Tickers from a hand-curated list of "good-mover" symbols, gets a +8 score bonus. |
| **Smart Exits** | Trailing-exit engine using ATR / EMA / HV signals plus an intraday emergency stop and EOD logic. |
| **Trade token** | `X-Trade-Token` — session-scoped gate for any write action. Memory only, never persisted. |
| **ASR** | Auto-Select Recommendation — picks the best contract by GEX score across an expiration calendar. |
| **`G`** | The global in-memory state object. Inspect from devtools: `console.log(G.results)`. |

---

## See also

- **`MAP.md`** — full subsystem index, line ranges, function-name → file-line index, "If X breaks, look here" cheat sheet.
- **`HANDOFF.md`** — paste-as-first-message brief that loads full project context into a new Claude session.
- **`worker/tradier-proxy/README.md`** — proxy operations runbook.
- **`industry/README.md`** — cron pipeline and theme-scoring methodology.

---

*Last updated: 2026-05-11 · v2.16.19 deploy*
