#!/usr/bin/env python3
"""
run_gex_cron.py
===============
Headless GEX/Flow scan run by GitHub Actions.

For each ticker in `gex/gex_universe.json`:
  1. Fetch /v1/markets/options/expirations  → pick nearest expiry in [25..50] DTE
  2. Fetch /v1/markets/options/chains for that expiry (greeks=true)
  3. Sum call OI, put OI, call vol, put vol
  4. Compute gamma-weighted net dealer GEX in $M per 1% spot move:
       gamma × OI × 100 × spot² × 0.01, calls +, puts − (standard dealer
       positioning assumption). Falls back to (call_oi − put_oi) × spot / 1M
       when greeks cover <50% of OI (row flagged gexProxy).
  5. Gamma flip = cumulative zero-cross strike (low→high); OI-proxy fallback
  6. Classify flow: CALL HEAVY ≥70%, CALL LEAN ≥55%, BALANCED, PUT LEAN ≤45%, PUT HEAVY ≤30%

Output: gex/gex_scores.json — a dict { ts, source, count, data: [...] }
where each row matches the in-page G.gexData UI schema directly:
    { t, gex, flip, call(%), put(%), callOI, putOI, callVol, putVol,
      dte, exp, price, flow("CALL HEAVY"/"PUT HEAVY"), flowCls("go"/"nogo") }

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
        params={"symbol": ticker, "expiration": expiry, "greeks": "true"},
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
    strikes = {}            # strike -> {"g": net gamma-$, "oi": combined OI}
    gamma_oi = tot_oi = 0   # greeks coverage accounting (OI-weighted)

    for o in opts:
        try:
            oi = int(o.get("open_interest") or 0)
            vol = int(o.get("volume") or 0)
            strike = float(o.get("strike") or 0)
            otype = (o.get("option_type") or "").lower()
        except (TypeError, ValueError):
            continue

        is_call = otype == "call"
        if is_call:
            call_oi += oi
            call_vol += vol
        elif otype == "put":
            put_oi += oi
            put_vol += vol
        else:
            continue
        tot_oi += oi

        if strike and oi > 0:
            ent = strikes.setdefault(strike, {"g": 0.0, "oi": 0})
            ent["oi"] += oi
            greeks = o.get("greeks") or {}
            try:
                gamma = float(greeks.get("gamma"))
            except (TypeError, ValueError):
                gamma = None
            if gamma is not None and spot > 0:
                gamma_oi += oi
                ent["g"] += gamma * oi * 100 * spot * spot * 0.01 * (1 if is_call else -1)

    total_oi = call_oi + put_oi
    if total_oi <= 0:
        return None

    # Zero-volume blend fix (matches in-page v6.12.26.8): OI-only when
    # option tape < 50 contracts. call_pct UNCLAMPED (legacy [10,90] clamp
    # removed — it hid extremes).
    total_vol = call_vol + put_vol or 1
    call_pct_oi = round((call_oi / total_oi) * 100)
    call_pct_vol = round((call_vol / total_vol) * 100)
    if (call_vol + put_vol) >= 50:
        call_pct = round(call_pct_oi * 0.6 + call_pct_vol * 0.4)
    else:
        call_pct = call_pct_oi

    # Gamma-weighted net GEX ($M per 1% move) + cumulative zero-cross flip.
    gex_proxy = not (tot_oi > 0 and spot > 0 and (gamma_oi / tot_oi) >= 0.5)
    ordered = sorted(strikes.keys())
    flip_strike = None
    flip_src = None
    if not gex_proxy:
        net_gex = round(sum(e["g"] for e in strikes.values()) / 1_000_000, 1)
        cum = 0.0
        prev = 0.0
        for i, k in enumerate(ordered):
            prev = cum
            cum += strikes[k]["g"]
            if i > 0 and ((prev < 0 <= cum) or (prev > 0 >= cum)):
                flip_strike = k
                flip_src = "gamma"
                break
    else:
        net_gex = round(((call_oi - put_oi) * spot) / 1_000_000, 1)
    if flip_strike is None:
        # OI proxy: max combined OI near ATM, widening to the whole chain.
        near = [k for k in ordered if abs(k - spot) <= spot * NEAR_ATM_PCT]
        pool = near or ordered
        if pool:
            flip_strike = max(pool, key=lambda k: strikes[k]["oi"])
            flip_src = "oi-atm" if near else "oi-chain"

    return {
        "t": ticker,
        "gex": net_gex,
        "gexProxy": gex_proxy,
        "flip": round(flip_strike, 2) if flip_strike is not None else None,
        "flipSrc": flip_src,
        "call": call_pct,
        "put": 100 - call_pct,
        "callOI": call_oi,
        "putOI": put_oi,
        "callVol": call_vol,
        "putVol": put_vol,
        "dte": dte,
        "exp": expiry,
        "price": round(spot, 2),
        "flow": "CALL HEAVY" if call_pct >= 50 else "PUT HEAVY",
        "flowCls": "go" if call_pct >= 50 else "nogo",
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
    rows.sort(key=lambda r: (0 if r["call"] >= 50 else 1, -r["gex"], -r["callOI"]))

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
