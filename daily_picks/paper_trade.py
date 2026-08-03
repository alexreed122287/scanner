#!/usr/bin/env python3
"""
paper_trade.py
==============
Paper-trade the daily bullish picks and email a running performance scorecard.

This is the companion to run_daily_picks.py. Where run_daily_picks.py *emails*
the morning's bullish call setups, this script *tracks* them as if you had
actually bought the top call contract for each pick, then reports how that
hypothetical book is doing.

Lifecycle, every run:
  1. OPEN  — derive today's bullish picks (same filter as run_daily_picks.py),
             pick the single best ITM/ATM call per ticker, and record a paper
             "buy" at the contract mid. Idempotent: re-running on the same day
             never double-opens the same contract.
  2. MARK  — re-price every still-open paper trade off a fresh Tradier quote
             and recompute unrealized P&L.
  3. CLOSE — realize a trade when its option expires (valued at intrinsic vs.
             the current spot) or once it has been held HOLD_DAYS calendar days.
  4. REPORT— email a scorecard (open book + recently closed + aggregate stats)
             via Resend, and persist the updated ledger.

The ledger is committed back to the repo by the workflow so state survives
across runs (GitHub Actions runners are ephemeral).

Sources (no fresh scan — reuses the committed cron snapshots):
  - gex/gex_scores.json        ← GEX cron (3×/day) — bullish flow + DTE
  - industry/theme_scores.json ← theme cron (daily) — sector / theme labels

Required env vars (same secrets as run_daily_picks.py):
  TRADIER_TOKEN   — Tradier live API token
  RESEND_API_KEY  — Resend account API key
  EMAIL_TO        — recipient address
  EMAIL_FROM      — Resend-verified sender address

Optional env vars:
  PAPER_MIN_CALL_PCT  — override the 70% bullish call-flow floor
  PAPER_MAX_OPENS     — cap on new paper trades opened per day (default 10)
  PAPER_HOLD_DAYS     — calendar days before a swing trade is force-closed (15)
  PAPER_LEDGER        — override the ledger path (default daily_picks/paper_ledger.json)
"""
import json
import os
import sys
import time
import html
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
GEX_SCORES = REPO_ROOT / "gex" / "gex_scores.json"
THEME_SCORES = REPO_ROOT / "industry" / "theme_scores.json"
LEDGER_PATH = Path(os.environ.get("PAPER_LEDGER") or (REPO_ROOT / "daily_picks" / "paper_ledger.json"))

BULLISH_CALL_PCT = int(os.environ.get("PAPER_MIN_CALL_PCT") or 70)
MAX_OPENS = int(os.environ.get("PAPER_MAX_OPENS") or 10)
HOLD_DAYS = int(os.environ.get("PAPER_HOLD_DAYS") or 15)
DTE_LO, DTE_HI = 25, 50

TRADIER_TOKEN = os.environ.get("TRADIER_TOKEN") or os.environ.get("TRADIER_LIVE_TOKEN")
RESEND_KEY = os.environ.get("RESEND_API_KEY")
EMAIL_TO = os.environ.get("EMAIL_TO")
EMAIL_FROM = os.environ.get("EMAIL_FROM")

CT = timezone(timedelta(hours=-6))


def _bail(msg, code=0):
    # Soft-fail (exit 0) on missing config so the scheduled workflow doesn't
    # spam failure notifications before the secrets are wired up — mirrors
    # run_daily_picks.py.
    sys.stderr.write("[paper-trade] " + msg + "\n")
    sys.exit(code)


if not TRADIER_TOKEN: _bail("TRADIER_TOKEN missing — skipping")
if not RESEND_KEY:    _bail("RESEND_API_KEY missing — set the secret to enable email")
if not EMAIL_TO:      _bail("EMAIL_TO missing — set the secret to enable email")
if not EMAIL_FROM:    _bail("EMAIL_FROM missing — set to a Resend-verified sender")

TRADIER_HOST = "https://api.tradier.com"
session = requests.Session()
session.headers.update({"Authorization": f"Bearer {TRADIER_TOKEN}", "Accept": "application/json"})


# ----------------------------------------------------------------------------
# Tradier helpers (kept self-contained so this script has no import-time
# coupling to run_daily_picks.py, whose module-level env checks would fire).
# ----------------------------------------------------------------------------
def _tradier_get(path, params=None, retries=3):
    url = TRADIER_HOST + path
    for attempt in range(retries):
        try:
            r = session.get(url, params=params, timeout=20)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            sys.stderr.write(f"[paper-trade] HTTP {r.status_code} on {url}\n")
            return None
        except requests.RequestException as e:
            sys.stderr.write(f"[paper-trade] {url} attempt {attempt+1}: {e}\n")
            time.sleep(1 + attempt)
    return None


def _mid(q):
    """Mid price from a Tradier quote dict, falling back to last/close."""
    try:
        bid = float(q.get("bid") or 0)
        ask = float(q.get("ask") or 0)
        if bid > 0 and ask > 0:
            return round((bid + ask) / 2, 2)
        last = float(q.get("last") or 0)
        if last > 0:
            return round(last, 2)
        close = float(q.get("close") or q.get("prevclose") or 0)
        return round(close, 2) if close > 0 else None
    except (TypeError, ValueError):
        return None


def fetch_quote(symbol):
    """Equity/option quote → dict with mid + day change %. None on failure."""
    data = _tradier_get("/v1/markets/quotes", {"symbols": symbol})
    if not data:
        return None
    try:
        q = data["quotes"]["quote"]
        if isinstance(q, list):
            q = q[0]
        return {
            "price": float(q.get("last") or q.get("close") or q.get("prevclose") or 0),
            "mid": _mid(q),
            "change_pct": float(q.get("change_percentage") or 0),
        }
    except (KeyError, TypeError, ValueError):
        return None


def fetch_best_call(symbol, expiry, spot):
    """Single best ITM/ATM call for an expiry — highest OI nearest spot.

    Mirrors run_daily_picks.fetch_top_calls' selection (0.95×–1.01× spot,
    OI ≥ 100, rank by OI then proximity) but returns only the top contract.
    """
    data = _tradier_get(
        "/v1/markets/options/chains",
        {"symbol": symbol, "expiration": expiry, "greeks": "true"},
    )
    if not data:
        return None
    try:
        opts = data["options"]["option"]
    except (KeyError, TypeError):
        return None
    if not isinstance(opts, list):
        opts = [opts]
    calls = []
    for o in opts:
        if (o.get("option_type") or "").lower() != "call":
            continue
        try:
            strike = float(o.get("strike") or 0)
            bid = float(o.get("bid") or 0)
            ask = float(o.get("ask") or 0)
            oi = int(o.get("open_interest") or 0)
        except (TypeError, ValueError):
            continue
        if strike <= 0 or (bid <= 0 and ask <= 0):
            continue
        if not (spot * 0.95 <= strike <= spot * 1.01):
            continue
        if oi < 100:
            continue
        mid = round((bid + ask) / 2, 2) if (bid and ask) else (bid or ask)
        delta = None
        try:
            d = (o.get("greeks") or {}).get("delta")
            delta = float(d) if d is not None else None
        except (TypeError, ValueError):
            pass
        calls.append({
            "strike": strike, "mid": mid, "oi": oi,
            "delta": delta, "symbol": o.get("symbol"),
        })
    if not calls:
        return None
    calls.sort(key=lambda c: (-c["oi"], abs(c["strike"] - spot)))
    return calls[0]


# ----------------------------------------------------------------------------
# Ledger
# ----------------------------------------------------------------------------
def load_ledger():
    if LEDGER_PATH.exists():
        try:
            led = json.loads(LEDGER_PATH.read_text())
            if isinstance(led, dict) and isinstance(led.get("trades"), list):
                return led
        except Exception as e:
            sys.stderr.write(f"[paper-trade] ledger load failed ({e}) — starting fresh\n")
    return {"version": 1, "updated": None, "trades": []}


def save_ledger(led):
    led["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    LEDGER_PATH.write_text(json.dumps(led, indent=2) + "\n")


def _today_ct():
    return datetime.now(CT).date()


def _parse_date(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------------------
# 1. OPEN — record today's bullish picks as paper buys
# ----------------------------------------------------------------------------
def derive_picks():
    gex = _load_json(GEX_SCORES) or {}
    rows = gex.get("data", [])
    bullish = []
    for r in rows:
        try:
            call_pct = float(r.get("call") or 0)
            net_gex = float(r.get("gex") or 0)
            dte = int(r.get("dte") or 0)
        except (TypeError, ValueError):
            continue
        if call_pct < BULLISH_CALL_PCT:
            continue
        if net_gex <= 0:
            continue
        if dte and not (DTE_LO <= dte <= DTE_HI):
            continue
        bullish.append(r)
    bullish.sort(key=lambda r: (-(r.get("gex") or 0), -(r.get("call") or 0)))
    return bullish[:MAX_OPENS]


def _load_json(path):
    try:
        return json.loads(path.read_text())
    except Exception as e:
        sys.stderr.write(f"[paper-trade] failed to load {path}: {e}\n")
        return None


def open_new_trades(led):
    today = _today_ct().isoformat()
    themes = _load_json(THEME_SCORES) or {}
    ticker2theme = themes.get("ticker2theme") or {}
    existing_ids = {t["id"] for t in led["trades"]}
    opened = []

    for p in derive_picks():
        sym = p.get("t")
        exp = p.get("exp")
        if not sym or not exp:
            continue
        q = fetch_quote(sym)
        time.sleep(0.3)
        spot = (q or {}).get("price") or p.get("price") or 0
        if not spot:
            continue
        best = fetch_best_call(sym, exp, spot)
        time.sleep(0.6)
        if not best or not best.get("symbol") or not best.get("mid"):
            continue
        tid = f"{sym}|{best['symbol']}|{today}"
        if tid in existing_ids:
            continue
        theme_info = ticker2theme.get(sym) or {}
        trade = {
            "id": tid,
            "ticker": sym,
            "occ": best["symbol"],
            "strike": best["strike"],
            "expiry": exp,
            "open_date": today,
            "entry_mid": best["mid"],
            "entry_spot": spot,
            "entry_delta": best.get("delta"),
            "sector": theme_info.get("sector") or "—",
            "theme": theme_info.get("theme") or "—",
            "status": "open",
            "last_mid": best["mid"],
            "last_date": today,
            "pnl_pct": 0.0,
            "close_date": None,
            "close_mid": None,
            "close_reason": None,
        }
        led["trades"].append(trade)
        existing_ids.add(tid)
        opened.append(trade)
    return opened


# ----------------------------------------------------------------------------
# 2/3. MARK + CLOSE — re-price open trades, realize the matured ones
# ----------------------------------------------------------------------------
def mark_and_close(led):
    today = _today_ct()
    newly_closed = []

    for t in led["trades"]:
        if t.get("status") != "open":
            continue
        expiry = _parse_date(t.get("expiry"))
        opened = _parse_date(t.get("open_date"))
        held_days = (today - opened).days if opened else 0

        # Re-price off the option's own quote.
        oq = fetch_quote(t["occ"])
        time.sleep(0.3)
        cur_mid = (oq or {}).get("mid")

        expired = expiry is not None and today >= expiry
        if expired:
            # Value at intrinsic against the current underlying spot — an
            # option quote past expiry is meaningless.
            sq = fetch_quote(t["ticker"])
            time.sleep(0.3)
            spot = (sq or {}).get("price") or 0
            cur_mid = round(max(spot - float(t["strike"]), 0.0), 2)

        if cur_mid is None:
            # Quote miss — keep the last known mark, try again next run.
            continue

        entry = float(t["entry_mid"]) or 0.0
        pnl_pct = round(((cur_mid - entry) / entry) * 100, 2) if entry else 0.0
        t["last_mid"] = cur_mid
        t["last_date"] = today.isoformat()
        t["pnl_pct"] = pnl_pct

        reason = None
        if expired:
            reason = "expiry"
        elif held_days >= HOLD_DAYS:
            reason = "max_hold"
        if reason:
            t["status"] = "closed"
            t["close_date"] = today.isoformat()
            t["close_mid"] = cur_mid
            t["close_reason"] = reason
            newly_closed.append(t)

    return newly_closed


# ----------------------------------------------------------------------------
# 4. REPORT
# ----------------------------------------------------------------------------
def _avg(vals):
    v = [x for x in vals if x is not None]
    return sum(v) / len(v) if v else None


def compute_stats(led):
    trades = led["trades"]
    opens = [t for t in trades if t.get("status") == "open"]
    closed = [t for t in trades if t.get("status") == "closed"]
    closed_pnls = [t.get("pnl_pct") for t in closed]
    open_pnls = [t.get("pnl_pct") for t in opens]
    wins = [p for p in closed_pnls if p is not None and p > 0]
    return {
        "n_open": len(opens),
        "n_closed": len(closed),
        "open_unreal_avg": _avg(open_pnls),
        "closed_realized_avg": _avg(closed_pnls),
        "win_rate": (len(wins) / len(closed_pnls)) if closed_pnls else None,
        "best_closed": max(closed_pnls) if closed_pnls else None,
        "worst_closed": min(closed_pnls) if closed_pnls else None,
    }


def render_email(led, opened, newly_closed, stats):
    today = datetime.now(CT).strftime("%A, %b %d %Y")

    def esc(s):
        return html.escape(str(s)) if s is not None else "—"

    def pct(v):
        if v is None:
            return "—"
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.2f}%"

    def pct_color(v):
        if v is None:
            return "#7090c8"
        return "#1d9e75" if v >= 0 else "#d85a30"

    def money(v):
        return f"${v:.2f}" if v not in (None, 0) else "—"

    def trade_rows(trades, closed=False):
        if not trades:
            label = "closed" if closed else "open"
            return (f"<tr><td colspan='6' style='padding:14px;text-align:center;"
                    f"color:#7090c8;font-size:12px;'>No {label} paper trades.</td></tr>")
        out = ""
        for t in sorted(trades, key=lambda x: (x.get("pnl_pct") or 0), reverse=True):
            p = t.get("pnl_pct")
            extra = (f"<span style='color:#7090c8;'> · {esc(t.get('close_reason'))}</span>"
                     if closed else
                     f"<span style='color:#7090c8;'> · opened {esc(t.get('open_date'))}</span>")
            out += f"""
            <tr style='border-top:1px solid #1a2735;'>
              <td style='padding:9px 12px;vertical-align:top;'>
                <div style='font-weight:700;font-size:14px;color:#00d4ff;letter-spacing:1px;'>{esc(t['ticker'])}</div>
                <div style='font-family:Menlo,monospace;font-size:10px;color:#7090c8;margin-top:2px;'>{esc(t.get('sector'))} · {esc(t.get('theme'))}</div>
              </td>
              <td style='padding:9px 12px;vertical-align:top;font-family:Menlo,monospace;font-size:11px;color:#cfd8dc;'>
                <b style='color:#00d4ff;'>${t['strike']:.2f}C</b> exp {esc(t['expiry'])}{extra}
              </td>
              <td style='padding:9px 12px;text-align:right;vertical-align:top;font-family:Menlo,monospace;font-size:12px;color:#cfd8dc;'>{money(t.get('entry_mid'))}</td>
              <td style='padding:9px 12px;text-align:right;vertical-align:top;font-family:Menlo,monospace;font-size:12px;color:#fff;'>{money(t.get('close_mid') if closed else t.get('last_mid'))}</td>
              <td style='padding:9px 12px;text-align:right;vertical-align:top;font-family:Menlo,monospace;font-size:13px;font-weight:700;color:{pct_color(p)};'>{pct(p)}</td>
            </tr>"""
        return out

    opens = [t for t in led["trades"] if t.get("status") == "open"]
    # Most-recently closed first, cap at 10 to keep the email tight.
    closed_sorted = sorted(
        [t for t in led["trades"] if t.get("status") == "closed"],
        key=lambda x: (x.get("close_date") or ""), reverse=True,
    )[:10]

    def stat_card(label, value, color="#fff"):
        return f"""
        <td style='padding:12px 10px;text-align:center;'>
          <div style='font-size:20px;font-weight:700;color:{color};font-family:Menlo,monospace;'>{value}</div>
          <div style='font-size:9px;letter-spacing:1.5px;color:#7090c8;margin-top:3px;'>{label}</div>
        </td>"""

    wr = stats["win_rate"]
    return f"""<!doctype html>
<html><body style='margin:0;padding:0;background:#050d14;font-family:-apple-system,BlinkMacSystemFont,sans-serif;color:#cfd8dc;'>
<table cellspacing='0' cellpadding='0' style='max-width:680px;margin:0 auto;background:#0a1521;border:1px solid #1a2735;border-radius:8px;width:100%;'>
  <tr>
    <td style='padding:18px 20px;border-bottom:1px solid #1a2735;background:linear-gradient(135deg,#0a1521,#0e1b2c);'>
      <div style='font-family:Orbitron,sans-serif;font-size:18px;letter-spacing:3px;color:#00d4ff;'>OPTION PANDA — PAPER TRADE PERFORMANCE</div>
      <div style='font-size:11px;color:#7090c8;margin-top:4px;letter-spacing:1px;'>{esc(today)} · {len(opened)} opened · {len(newly_closed)} closed today</div>
    </td>
  </tr>
  <tr><td style='padding:6px 12px;'>
    <table cellspacing='0' cellpadding='0' style='width:100%;border-collapse:collapse;'>
      <tr>
        {stat_card("OPEN", stats["n_open"])}
        {stat_card("UNREAL P/L", pct(stats["open_unreal_avg"]), pct_color(stats["open_unreal_avg"]))}
        {stat_card("CLOSED", stats["n_closed"])}
        {stat_card("REALIZED P/L", pct(stats["closed_realized_avg"]), pct_color(stats["closed_realized_avg"]))}
        {stat_card("WIN RATE", (f"{wr*100:.0f}%" if wr is not None else "—"))}
      </tr>
    </table>
  </td></tr>
  <tr><td style='padding:6px 20px 2px;font-size:10px;letter-spacing:2px;color:#7090c8;font-weight:700;'>OPEN BOOK ({len(opens)})</td></tr>
  <tr><td style='padding:0 8px;'>
    <table cellspacing='0' cellpadding='0' style='width:100%;border-collapse:collapse;'>
      <thead><tr style='background:#0e1b2c;'>
        <th style='padding:7px 12px;text-align:left;font-size:9px;letter-spacing:1.5px;color:#7090c8;'>TICKER</th>
        <th style='padding:7px 12px;text-align:left;font-size:9px;letter-spacing:1.5px;color:#7090c8;'>CONTRACT</th>
        <th style='padding:7px 12px;text-align:right;font-size:9px;letter-spacing:1.5px;color:#7090c8;'>ENTRY</th>
        <th style='padding:7px 12px;text-align:right;font-size:9px;letter-spacing:1.5px;color:#7090c8;'>MARK</th>
        <th style='padding:7px 12px;text-align:right;font-size:9px;letter-spacing:1.5px;color:#7090c8;'>P/L</th>
      </tr></thead>
      <tbody>{trade_rows(opens, closed=False)}</tbody>
    </table>
  </td></tr>
  <tr><td style='padding:14px 20px 2px;font-size:10px;letter-spacing:2px;color:#7090c8;font-weight:700;'>RECENTLY CLOSED</td></tr>
  <tr><td style='padding:0 8px;'>
    <table cellspacing='0' cellpadding='0' style='width:100%;border-collapse:collapse;'>
      <thead><tr style='background:#0e1b2c;'>
        <th style='padding:7px 12px;text-align:left;font-size:9px;letter-spacing:1.5px;color:#7090c8;'>TICKER</th>
        <th style='padding:7px 12px;text-align:left;font-size:9px;letter-spacing:1.5px;color:#7090c8;'>CONTRACT</th>
        <th style='padding:7px 12px;text-align:right;font-size:9px;letter-spacing:1.5px;color:#7090c8;'>ENTRY</th>
        <th style='padding:7px 12px;text-align:right;font-size:9px;letter-spacing:1.5px;color:#7090c8;'>EXIT</th>
        <th style='padding:7px 12px;text-align:right;font-size:9px;letter-spacing:1.5px;color:#7090c8;'>P/L</th>
      </tr></thead>
      <tbody>{trade_rows(closed_sorted, closed=True)}</tbody>
    </table>
  </td></tr>
  <tr>
    <td style='padding:14px 20px;border-top:1px solid #1a2735;font-size:10px;color:#445566;line-height:1.6;'>
      Hypothetical paper book — one ITM/ATM call per daily bullish pick, entered at the contract mid,
      held to expiry or {HOLD_DAYS} days. Generated by the paper_trade GitHub Action.
      <a href='https://alexreed122287.github.io/scanner/' style='color:#00d4ff;text-decoration:none;'>Open the dashboard</a>.
      <br>Not financial advice. Paper results do not reflect slippage, fills, or commissions.
    </td>
  </tr>
</table>
</body></html>"""


def send_email(html_body, stats):
    subject_date = datetime.now(CT).strftime("%b %d")
    realized = stats["closed_realized_avg"]
    tag = f"{realized:+.1f}% realized" if realized is not None else f"{stats['n_open']} open"
    subject = f"Option Panda — Paper P/L ({tag}, {subject_date})"
    r = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {RESEND_KEY}", "Content-Type": "application/json"},
        json={"from": EMAIL_FROM, "to": [EMAIL_TO], "subject": subject, "html": html_body},
        timeout=20,
    )
    if r.status_code >= 400:
        sys.stderr.write(f"[paper-trade] Resend error {r.status_code}: {r.text[:400]}\n")
        sys.exit(1)
    sys.stderr.write(f"[paper-trade] sent → {EMAIL_TO} ({stats['n_open']} open, {stats['n_closed']} closed)\n")


def main():
    led = load_ledger()
    opened = open_new_trades(led)
    newly_closed = mark_and_close(led)
    stats = compute_stats(led)
    save_ledger(led)
    html_body = render_email(led, opened, newly_closed, stats)
    send_email(html_body, stats)


if __name__ == "__main__":
    main()
