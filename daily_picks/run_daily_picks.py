#!/usr/bin/env python3
"""
run_daily_picks.py
==================
Compose + send the daily morning picks email.

Sources used (no fresh scan run — relies on the already-committed snapshots
the other crons keep up to date):
  - gex/gex_scores.json     ← GEX cron (3×/day) — bullish flow + suggested call
  - industry/theme_scores.json ← theme cron (daily) — sector + theme strength

Filter: bullish setups only.
  call % ≥ BULLISH_CALL_PCT (70 — matches the in-page BULLISH_CALL_PCT)
  AND net GEX > 0 (positive-gamma drift zone)
  AND DTE in [25, 50]

For each pick we re-fetch the live Tradier options chain to surface the top 3
ITM/ATM call contracts (strike, expiry, mid premium, OI) and a fresh quote
(price + day-change %). The GEX snapshot's "suggested" contract is included
as a baseline candidate.

Email is sent via Resend (https://resend.com — free tier is fine for daily
single-recipient mail). Required env vars:
  TRADIER_TOKEN     — Tradier live API token (already configured for GEX cron)
  RESEND_API_KEY    — Resend account API key
  EMAIL_TO          — recipient address
  EMAIL_FROM        — sender address (must be a domain you verified at Resend)

Optional env vars:
  DAILY_PICKS_MIN_CALL_PCT  — override the 70% floor (e.g. 65)
  DAILY_PICKS_MAX_PICKS     — cap on number of tickers in the email (default 10)
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

BULLISH_CALL_PCT = int(os.environ.get("DAILY_PICKS_MIN_CALL_PCT") or 70)
MAX_PICKS = int(os.environ.get("DAILY_PICKS_MAX_PICKS") or 10)
TOP_N_CONTRACTS = 3                   # contracts per ticker in the email
DTE_LO, DTE_HI = 25, 50

TRADIER_TOKEN = os.environ.get("TRADIER_TOKEN") or os.environ.get("TRADIER_LIVE_TOKEN")
RESEND_KEY = os.environ.get("RESEND_API_KEY")
EMAIL_TO = os.environ.get("EMAIL_TO")
EMAIL_FROM = os.environ.get("EMAIL_FROM")

# Soft-fail when env is incomplete so the workflow exits 0 with a clear log
# (vs failing the actions run, which spams the user with notifications).
def _bail(msg):
    sys.stderr.write("[daily-picks] " + msg + "\n")
    sys.exit(0)

if not TRADIER_TOKEN: _bail("TRADIER_TOKEN missing — skipping")
if not RESEND_KEY:    _bail("RESEND_API_KEY missing — set the secret to enable email")
if not EMAIL_TO:      _bail("EMAIL_TO missing — set the secret to enable email")
if not EMAIL_FROM:    _bail("EMAIL_FROM missing — set to a Resend-verified sender")

TRADIER_HOST = "https://api.tradier.com"
TRADIER_HEADERS = {"Authorization": f"Bearer {TRADIER_TOKEN}", "Accept": "application/json"}
session = requests.Session()
session.headers.update(TRADIER_HEADERS)


def _load_json(path):
    try:
        return json.loads(path.read_text())
    except Exception as e:
        sys.stderr.write(f"[daily-picks] failed to load {path}: {e}\n")
        return None


def _tradier_get(path, params=None, retries=3):
    """GET with backoff. Returns parsed JSON or None on failure."""
    url = TRADIER_HOST + path
    for attempt in range(retries):
        try:
            r = session.get(url, params=params, timeout=20)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            sys.stderr.write(f"[daily-picks] HTTP {r.status_code} on {url}\n")
            return None
        except requests.RequestException as e:
            sys.stderr.write(f"[daily-picks] {url} attempt {attempt+1}: {e}\n")
            time.sleep(1 + attempt)
    return None


def fetch_quote(symbol):
    """Returns dict with price, change_pct, day_high, day_low — or None."""
    data = _tradier_get("/v1/markets/quotes", {"symbols": symbol})
    if not data:
        return None
    try:
        q = data["quotes"]["quote"]
        if isinstance(q, list):
            q = q[0]
        return {
            "price": float(q.get("last") or q.get("close") or q.get("prevclose") or 0),
            "change_pct": float(q.get("change_percentage") or 0),
            "high": float(q.get("high") or 0),
            "low":  float(q.get("low")  or 0),
        }
    except (KeyError, TypeError, ValueError):
        return None


def fetch_top_calls(symbol, expiry, spot, top_n=TOP_N_CONTRACTS):
    """For one expiry, return up to top_n call contracts (strike/bid/ask/mid/oi)
    biased toward ITM-to-slightly-ITM with reasonable liquidity."""
    data = _tradier_get(
        "/v1/markets/options/chains",
        {"symbol": symbol, "expiration": expiry, "greeks": "true"},
    )
    if not data:
        return []
    try:
        opts = data["options"]["option"]
    except (KeyError, TypeError):
        return []
    if not isinstance(opts, list):
        opts = [opts]
    calls = []
    for o in opts:
        if (o.get("option_type") or "").lower() != "call":
            continue
        try:
            strike = float(o.get("strike") or 0)
            bid    = float(o.get("bid") or 0)
            ask    = float(o.get("ask") or 0)
            oi     = int(o.get("open_interest") or 0)
        except (TypeError, ValueError):
            continue
        if strike <= 0 or (bid <= 0 and ask <= 0):
            continue
        mid = round((bid + ask) / 2, 2) if (bid and ask) else (bid or ask)
        # Bias toward 0.5–3% ITM where delta is around 0.55–0.75 — sweet spot
        # for the "first long-call entry" use case.
        if not (spot * 0.95 <= strike <= spot * 1.01):
            continue
        if oi < 100:                      # liquidity floor for retail size
            continue
        delta = None
        try:
            greeks = o.get("greeks") or {}
            d = greeks.get("delta")
            delta = float(d) if d is not None else None
        except (TypeError, ValueError):
            pass
        calls.append({
            "strike": strike, "bid": bid, "ask": ask, "mid": mid,
            "oi": oi, "delta": delta, "symbol": o.get("symbol")
        })
    # Rank by OI desc (proxy for liquidity / institutional comfort)
    calls.sort(key=lambda c: (-c["oi"], abs(c["strike"] - spot)))
    return calls[:top_n]


def build_picks():
    gex = _load_json(GEX_SCORES) or {}
    rows = gex.get("data", [])
    if not rows:
        _bail("gex_scores.json is empty — nothing to do")

    themes = _load_json(THEME_SCORES) or {}
    # theme_scores.json has shape: { themes: [{name, dailyScore, members:[...]}], ticker2theme: {...} }
    ticker2theme = themes.get("ticker2theme") or {}

    bullish = []
    for r in rows:
        try:
            call_pct = float(r.get("call") or 0)
            net_gex  = float(r.get("gex")  or 0)
            dte      = int(r.get("dte")   or 0)
        except (TypeError, ValueError):
            continue
        if call_pct < BULLISH_CALL_PCT: continue
        if net_gex  <= 0:               continue
        if dte and not (DTE_LO <= dte <= DTE_HI): continue
        bullish.append(r)

    # Rank by net GEX desc — the strongest dealer-positioning convictions
    bullish.sort(key=lambda r: (-(r.get("gex") or 0), -(r.get("call") or 0)))
    picks = bullish[:MAX_PICKS]
    if not picks:
        return [], gex.get("ts")

    enriched = []
    for p in picks:
        sym = p.get("t")
        if not sym: continue
        quote = fetch_quote(sym) or {}
        time.sleep(0.3)
        contracts = fetch_top_calls(sym, p.get("exp"), quote.get("price") or p.get("price") or 0)
        time.sleep(0.6)
        theme_info = ticker2theme.get(sym) or {}
        enriched.append({
            "ticker": sym,
            "price": quote.get("price") or p.get("price"),
            "change_pct": quote.get("change_pct") or 0,
            "call_pct": p.get("call"),
            "net_gex": p.get("gex"),
            "dte": p.get("dte"),
            "exp": p.get("exp"),
            "sector": theme_info.get("sector") or "—",
            "theme":  theme_info.get("theme")  or "—",
            "theme_score": theme_info.get("dailyScore"),
            "contracts": contracts,
        })

    return enriched, gex.get("ts")


def render_email(picks, gex_ts_ms):
    today = datetime.now(timezone(timedelta(hours=-6))).strftime("%A, %b %d %Y")
    gex_ts = ""
    if gex_ts_ms:
        gex_ts = datetime.fromtimestamp(gex_ts_ms/1000, timezone(timedelta(hours=-6))).strftime("%Y-%m-%d %I:%M %p CT")

    def esc(s): return html.escape(str(s)) if s is not None else "—"
    def fmt_pct(v):
        if v is None: return "—"
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.2f}%"
    def fmt_price(v):
        if v is None or v == 0: return "—"
        return f"${v:.2f}"

    if not picks:
        body_rows = "<tr><td colspan='6' style='padding:16px;text-align:center;color:#7090c8;'>No bullish setups passed the filter this morning.</td></tr>"
    else:
        body_rows = ""
        for p in picks:
            chg_color = "#1d9e75" if (p["change_pct"] or 0) >= 0 else "#d85a30"
            contract_lines = ""
            if p["contracts"]:
                for c in p["contracts"]:
                    delta_str = f" δ={c['delta']:.2f}" if c.get("delta") is not None else ""
                    contract_lines += (
                        f"<div style='font-family:Menlo,monospace;font-size:11px;color:#cfd8dc;'>"
                        f"<b style='color:#00d4ff;'>${c['strike']:.2f}C</b> "
                        f"exp {esc(p['exp'])} · "
                        f"<b style='color:#1d9e75;'>${c['mid']:.2f}</b> "
                        f"<span style='color:#7090c8;'>(bid {c['bid']:.2f}/ask {c['ask']:.2f}, OI {c['oi']}{delta_str})</span>"
                        f"</div>"
                    )
            else:
                contract_lines = "<div style='font-family:Menlo,monospace;font-size:11px;color:#7090c8;'>no liquid ITM calls found</div>"

            body_rows += f"""
            <tr style='border-top:1px solid #1a2735;'>
              <td style='padding:10px 12px;vertical-align:top;'>
                <div style='font-weight:700;font-size:15px;color:#00d4ff;letter-spacing:1px;'>{esc(p['ticker'])}</div>
                <div style='font-family:Menlo,monospace;font-size:10px;color:#7090c8;margin-top:2px;'>{esc(p['sector'])} · {esc(p['theme'])}</div>
              </td>
              <td style='padding:10px 12px;vertical-align:top;text-align:right;font-family:Menlo,monospace;'>
                <div style='font-size:13px;color:#fff;font-weight:600;'>{fmt_price(p['price'])}</div>
                <div style='font-size:11px;color:{chg_color};margin-top:2px;'>{fmt_pct(p['change_pct'])}</div>
              </td>
              <td style='padding:10px 12px;vertical-align:top;text-align:right;font-family:Menlo,monospace;font-size:11px;color:#cfd8dc;'>
                {esc(p['call_pct'])}% call<br>
                <span style='color:#7090c8;'>{esc(round(p['net_gex'], 1)) if isinstance(p['net_gex'], (int, float)) else esc(p['net_gex'])}M GEX</span>
              </td>
              <td colspan='3' style='padding:10px 12px;vertical-align:top;'>
                {contract_lines}
              </td>
            </tr>
            """

    minfp = BULLISH_CALL_PCT
    return f"""<!doctype html>
<html><body style='margin:0;padding:0;background:#050d14;font-family:-apple-system,BlinkMacSystemFont,sans-serif;color:#cfd8dc;'>
<table cellspacing='0' cellpadding='0' style='max-width:680px;margin:0 auto;background:#0a1521;border:1px solid #1a2735;border-radius:8px;width:100%;'>
  <tr>
    <td style='padding:18px 20px;border-bottom:1px solid #1a2735;background:linear-gradient(135deg,#0a1521,#0e1b2c);'>
      <div style='font-family:Orbitron,sans-serif;font-size:18px;letter-spacing:3px;color:#00d4ff;'>OPTION PANDA — DAILY PICKS</div>
      <div style='font-size:11px;color:#7090c8;margin-top:4px;letter-spacing:1px;'>{esc(today)} · {len(picks)} bullish setups · call%≥{minfp}, net GEX&gt;0</div>
      <div style='font-size:10px;color:#445566;margin-top:2px;font-family:Menlo,monospace;'>GEX snapshot: {esc(gex_ts)}</div>
    </td>
  </tr>
  <tr>
    <td>
      <table cellspacing='0' cellpadding='0' style='width:100%;border-collapse:collapse;'>
        <thead>
          <tr style='background:#0e1b2c;'>
            <th style='padding:8px 12px;text-align:left;font-size:9px;letter-spacing:2px;color:#7090c8;font-weight:700;'>TICKER · SECTOR / THEME</th>
            <th style='padding:8px 12px;text-align:right;font-size:9px;letter-spacing:2px;color:#7090c8;font-weight:700;'>PRICE</th>
            <th style='padding:8px 12px;text-align:right;font-size:9px;letter-spacing:2px;color:#7090c8;font-weight:700;'>FLOW</th>
            <th colspan='3' style='padding:8px 12px;text-align:left;font-size:9px;letter-spacing:2px;color:#7090c8;font-weight:700;'>TOP {TOP_N_CONTRACTS} CALL CONTRACTS</th>
          </tr>
        </thead>
        <tbody>{body_rows}</tbody>
      </table>
    </td>
  </tr>
  <tr>
    <td style='padding:14px 20px;border-top:1px solid #1a2735;font-size:10px;color:#445566;line-height:1.6;'>
      Generated by the daily_picks GitHub Action. Open the dashboard for live data + the full scorecard:
      <a href='https://alexreed122287.github.io/scanner/' style='color:#00d4ff;text-decoration:none;'>alexreed122287.github.io/scanner</a>.
      <br>This is not financial advice. Always verify with your own analysis before placing trades.
    </td>
  </tr>
</table>
</body></html>"""


def send_email(html_body, n_picks):
    subject_date = datetime.now(timezone(timedelta(hours=-6))).strftime("%b %d")
    subject = f"Option Panda — {n_picks} bullish picks ({subject_date})"
    payload = {
        "from": EMAIL_FROM,
        "to": [EMAIL_TO],
        "subject": subject,
        "html": html_body,
    }
    r = requests.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {RESEND_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=20,
    )
    if r.status_code >= 400:
        sys.stderr.write(f"[daily-picks] Resend error {r.status_code}: {r.text[:400]}\n")
        sys.exit(1)
    sys.stderr.write(f"[daily-picks] sent → {EMAIL_TO} ({n_picks} picks)\n")


def main():
    picks, gex_ts = build_picks()
    html_body = render_email(picks, gex_ts)
    send_email(html_body, len(picks))


if __name__ == "__main__":
    main()
