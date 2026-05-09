#!/usr/bin/env python3
"""
run_gex_cron.py
===============
Headless GEX/Flow scan run by GitHub Actions.

For each ticker in `gex/gex_universe.json`:
  1. Fetch /v1/markets/options/expirations  → pick nearest expiry in [25..50] DTE
  2. Fetch /v1/markets/options/chains for that expiry
  3. Sum call OI, put OI, call vol, put vol
  4. Compute net GEX = (call_oi − put_oi) × spot / 1_000_000
  5. Pick gamma-flip strike (highest combined OI within ±10% of spot)
  6. Classify flow: CALL HEAVY ≥70%, CALL LEAN ≥55%, BALANCED, PUT LEAN ≤45%, PUT HEAVY ≤30%

Output: gex/gex_scores.json — a dict { ts, source, count, data: [...] }
where each row matches the in-page G.gexData schema:
    { t, gex, flip, call, put, callOI, putOI, dte, exp, price, flow, flowCls }

Auth: TRADIER_TOKEN env var (live token — sandbox doesn't return real OI).
Pacing: 600 ms between dispatches (matches the in-page GEX_DISPATCH_MS).
"""

import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
UNIVERSE_PATH = REPO_ROOT / "gex" / "gex_universe.json"
OUTPUT_PATH = REPO_ROOT / "gex" / "gex_scores.json"

TRADIER_TOKEN = os.environ.get("TRADIER_TOKEN") or os.environ.get("TRADIER_LIVE_TOKEN")
if not TRADIER_TOKEN:
    sys.stderr.write("FATAL: TRADIER_TOKEN env var not set.\n")
    sys.exit(1)

TRADIER_HOST = "https://api.tradier.com"  # live only — sandbox OI is fake
HEADERS = {"Authorization": f"Bearer {TRADIER_TOKEN}", "Accept": "application/json"}

DISPATCH_MS = 600           # 600 ms between calls — matches in-page pacing
TARGET_DTE_LO = 25
TARGET_DTE_HI = 50
NEAR_ATM_PCT = 0.10         # ±10% of spot for flip-strike search

session = requests.Session()
session.headers.update(HEADERS)


def _today_et():
    """ET 'today' as a date object — for DTE math. ET handles DST automatically."""
    # Python doesn't have a built-in for IANA timezones without zoneinfo (3.9+).
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York")).date()
    except Exception:
        # Fallback: assume UTC-5 (works ~half the year). Acceptable degradation.
        return (datetime.now(timezone.utc) - timedelta(hours=5)).date()


def _fetch(url, params=None, retries=3):
    """GET with exponential backoff. Returns parsed JSON or None on hard fail."""
    for attempt in range(retries):
        try:
            r = session.get(url, params=params, timeout=20)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                # Rate limited. Sleep + retry.
                time.sleep(2 ** attempt)
                continue
            sys.stderr.write(f"[gex] HTTP {r.status_code} on {url}: {r.text[:200]}\n")
            return None
        except (requests.RequestException, ValueError) as e:
            sys.stderr.write(f"[gex] {url} attempt {attempt+1} failed: {e}\n")
            time.sleep(1 + attempt)
    return None


def _spot_for(ticker):
    """Last/close from /v1/markets/quotes."""
    data = _fetch(f"{TRADIER_HOST}/v1/markets/quotes", params={"symbols": ticker})
    if not data:
        return None
    try:
        q = data["quotes"]["quote"]
        if isinstance(q, list):
            q = q[0]
        return float(q.get("last") or q.get("close") or q.get("prevclose") or 0) or None
    except (KeyError, TypeError, ValueError):
        return None


def _pick_expiry(ticker):
    """Nearest expiry in [25..50] DTE; falls back to closest if none in window."""
    data = _fetch(
        f"{TRADIER_HOST}/v1/markets/options/expirations",
        params={"symbol": ticker, "includeAllRoots": "true"},
    )
    if not data:
        return None
    try:
        dates = data["expirations"]["date"]
    except (KeyError, TypeError):
        return None
    if isinstance(dates, str):
        dates = [dates]
    if not dates:
        return None

    today = _today_et()
    best = None
    best_distance = 10**9
    for d in dates:
        try:
            ed = datetime.strptime(d, "%Y-%m-%d").date()
        except ValueError:
            continue
        dte = (ed - today).days
        if dte < 1:
            continue
        # Prefer in-window; otherwise distance from window center (37 DTE).
        if TARGET_DTE_LO <= dte <= TARGET_DTE_HI:
            score = abs(dte - 37)
        else:
            score = 100 + abs(dte - 37)  # heavy penalty for out-of-window
        if score < best_distance:
            best_distance = score
            best = (d, dte)
    return best


def _fetch_chain(ticker, expiry):
    data = _fetch(
        f"{TRADIER_HOST}/v1/markets/options/chains",
        params={"symbol": ticker, "expiration": expiry, "greeks": "false"},
    )
    if not data:
        return None
    try:
        opts = data["options"]["option"]
    except (KeyError, TypeError):
        return None
    if not isinstance(opts, list):
        opts = [opts]
    return opts


def _compute_row(ticker, spot, expiry, dte, opts):
    """Match the in-page G.gexData row schema exactly."""
    if not spot or spot <= 0:
        return None

    call_oi = put_oi = 0
    call_vol = put_vol = 0
    flip_strike = spot
    flip_oi = 0

    for o in opts:
        try:
            oi = int(o.get("open_interest") or 0)
            vol = int(o.get("volume") or 0)
            strike = float(o.get("strike") or 0)
            otype = (o.get("option_type") or "").lower()
        except (TypeError, ValueError):
            continue

        if otype == "call":
            call_oi += oi
            call_vol += vol
        elif otype == "put":
            put_oi += oi
            put_vol += vol

        # Flip = highest combined OI within ±10% of spot.
        if abs(strike - spot) <= spot * NEAR_ATM_PCT:
            if oi > flip_oi:
                flip_oi = oi
                flip_strike = strike

    total_oi = call_oi + put_oi
    if total_oi <= 0:
        return None

    call_pct = (call_oi / total_oi) * 100
    # Net GEX in millions — same scaling as the page.
    net_gex = round(((call_oi - put_oi) * spot) / 1_000_000, 2)

    # Flow classification matches in-page thresholds.
    if call_pct >= 70:
        flow_cls = "CALL HEAVY"
    elif call_pct >= 55:
        flow_cls = "CALL LEAN"
    elif call_pct <= 30:
        flow_cls = "PUT HEAVY"
    elif call_pct <= 45:
        flow_cls = "PUT LEAN"
    else:
        flow_cls = "BALANCED"

    return {
        "t": ticker,
        "gex": net_gex,
        "flip": round(flip_strike, 2),
        "call": call_vol,
        "put": put_vol,
        "callOI": call_oi,
        "putOI": put_oi,
        "dte": dte,
        "exp": expiry,
        "price": round(spot, 2),
        "flow": round(call_pct, 1),
        "flowCls": flow_cls,
    }


def main():
    universe = json.loads(UNIVERSE_PATH.read_text())
    tickers = universe.get("tickers", [])
    if not tickers:
        sys.stderr.write("FATAL: no tickers in universe file.\n")
        sys.exit(1)

    print(f"[gex] scanning {len(tickers)} tickers, ~{len(tickers) * 3 * DISPATCH_MS / 1000:.0f}s minimum")
    rows = []
    skipped = 0
    started = time.time()

    for i, t in enumerate(tickers):
        if i and i % 25 == 0:
            print(f"[gex] {i}/{len(tickers)} · {len(rows)} rows · skipped {skipped} · elapsed {int(time.time()-started)}s")

        spot = _spot_for(t)
        time.sleep(DISPATCH_MS / 1000)
        if not spot:
            skipped += 1
            continue

        picked = _pick_expiry(t)
        time.sleep(DISPATCH_MS / 1000)
        if not picked:
            skipped += 1
            continue
        expiry, dte = picked

        opts = _fetch_chain(t, expiry)
        time.sleep(DISPATCH_MS / 1000)
        if not opts:
            skipped += 1
            continue

        row = _compute_row(t, spot, expiry, dte, opts)
        if row:
            rows.append(row)
        else:
            skipped += 1

    if not rows:
        sys.stderr.write("FATAL: no rows produced — aborting before write so old snapshot stays.\n")
        sys.exit(1)

    # Sort: bullish (call %≥50) first by net GEX desc, then put-heavy by net GEX desc.
    rows.sort(key=lambda r: (0 if r["flow"] >= 50 else 1, -r["gex"], -r["callOI"]))

    out = {
        "ts": int(time.time() * 1000),
        "source": "github-cron",
        "count": len(rows),
        "skipped": skipped,
        "universe_size": len(tickers),
        "data": rows,
    }
    OUTPUT_PATH.write_text(json.dumps(out, indent=2))
    print(f"[gex] wrote {OUTPUT_PATH} — {len(rows)} rows, {skipped} skipped, {int(time.time()-started)}s total")


if __name__ == "__main__":
    main()
