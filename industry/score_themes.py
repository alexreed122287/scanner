#!/usr/bin/env python3
"""
score_themes.py
===============
Daily theme/industry strength scoring engine.

Reads master_tickers.json, pulls 200 days of daily bars via yfinance for SPY +
all theme members + TV-sector members, then computes a multi-timeframe relative
strength score for every theme.

Methodology (the score, in plain English):
------------------------------------------
For each theme, we compute an equal-weighted return series from its members.
Then we measure how that theme has done vs SPY over four windows:
    1W = last 5 trading days
    1M = last 21 trading days
    3M = last 63 trading days
    6M = last 126 trading days

Each theme is percentile-ranked (0-100) against ALL other themes within each
window. So an RS_1M of 90 means this theme outperformed SPY in the last month
better than 90% of peer themes did. This is the same idea as IBD's RS Rating
but applied at the theme level.

We also compute:
    breadth_50  = % of theme members whose price > their 50-day SMA
    breadth_200 = % of theme members whose price > their 200-day SMA
    trend       = +1 if theme composite > 50-EMA, else 0

Then three composite scores are produced — they share inputs but weight
short vs intermediate momentum differently:

    DAILY   = 0.50 * RS_1W + 0.25 * RS_1M + 0.15 * Breadth50 + 0.10 * Trend*100
    WEEKLY  = 0.20 * RS_1W + 0.50 * RS_1M + 0.15 * RS_3M + 0.15 * Breadth50
    MONTHLY = 0.15 * RS_1M + 0.40 * RS_3M + 0.30 * RS_6M + 0.15 * Breadth200

Themes ranked in the top decile across all three timeframes are the cleanest
signals — short, intermediate, and longer-term momentum aligning is rare and
historically the strongest leading indicator of continued sector leadership.

Output: theme_scores.json (consumed by themes.html).
"""

import json
import os
import sys
import time
import warnings
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf

warnings.filterwarnings("ignore", category=FutureWarning)

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "industry" / "master_tickers.json"
OUT_JSON = ROOT / "industry" / "theme_scores.json"
HISTORY_JSON = ROOT / "industry" / "theme_scores_history.json"

LOOKBACK_DAYS = 260
BENCHMARK = "SPY"

WINDOWS = {"1W": 5, "1M": 21, "3M": 63, "6M": 126}

TRADIER_TOKEN = os.environ.get("TRADIER_TOKEN", "")
TRADIER_BASE = "https://api.tradier.com/v1"  # production endpoint


# ---------------------------------------------------------------------------
# Data fetching — Tradier primary (if token), yfinance fallback
# ---------------------------------------------------------------------------

def fetch_tradier_history(ticker: str, start: str, end: str,
                          session: requests.Session) -> pd.Series | None:
    """One ticker via Tradier /v1/markets/history (daily)."""
    try:
        r = session.get(
            f"{TRADIER_BASE}/markets/history",
            params={"symbol": ticker, "interval": "daily",
                    "start": start, "end": end},
            headers={"Authorization": f"Bearer {TRADIER_TOKEN}",
                     "Accept": "application/json"},
            timeout=10,
        )
        if r.status_code != 200:
            return None
        data = r.json().get("history")
        if not data or "day" not in data:
            return None
        days = data["day"]
        if isinstance(days, dict):
            days = [days]
        dates, closes = [], []
        for d in days:
            dates.append(pd.Timestamp(d["date"]))
            closes.append(float(d["close"]))
        s = pd.Series(closes, index=pd.DatetimeIndex(dates), name=ticker)
        return s if len(s) > 50 else None
    except Exception:
        return None


def fetch_prices_tradier(tickers: list[str], days: int) -> pd.DataFrame:
    """Sequential per-ticker fetch via Tradier. ~60 req/min limit on free tier
    so we throttle to 50/min to be safe."""
    end = datetime.now(timezone.utc).replace(tzinfo=None)
    start = end - timedelta(days=int(days * 1.5))
    start_s = start.strftime("%Y-%m-%d")
    end_s = end.strftime("%Y-%m-%d")
    print(f"  TRADIER fetch: {len(tickers)} tickers (throttled 50/min)...",
          flush=True)

    sess = requests.Session()
    closes: dict[str, pd.Series] = {}
    for i, tkr in enumerate(tickers, 1):
        s = fetch_tradier_history(tkr, start_s, end_s, sess)
        if s is not None:
            closes[tkr] = s
        if i % 50 == 0:
            print(f"    {i}/{len(tickers)}  cumulative={len(closes)}", flush=True)
        time.sleep(1.2)  # 50 req/min
    out = pd.DataFrame(closes)
    print(f"  Tradier got {out.shape[1]}/{len(tickers)} tickers, "
          f"{out.shape[0]} bars", flush=True)
    return out


def fetch_prices_yfinance(tickers: list[str], days: int = LOOKBACK_DAYS,
                          chunk_size: int = 100) -> pd.DataFrame:
    """Fallback: yfinance in chunks. Works fine from GitHub Actions runners
    but may rate-limit elsewhere."""
    end = datetime.now(timezone.utc).replace(tzinfo=None)
    start = end - timedelta(days=int(days * 1.5))
    start_s = start.strftime("%Y-%m-%d")
    end_s = end.strftime("%Y-%m-%d")
    print(f"  YFINANCE fetch: {len(tickers)} tickers in chunks of {chunk_size}...",
          flush=True)

    closes: dict[str, pd.Series] = {}
    chunks = [tickers[i:i + chunk_size]
              for i in range(0, len(tickers), chunk_size)]

    for i, chunk in enumerate(chunks, 1):
        try:
            df = yf.download(
                tickers=chunk, start=start_s, end=end_s,
                auto_adjust=True, progress=False, threads=True,
                group_by="ticker",
            )
        except Exception as e:
            print(f"    chunk {i}/{len(chunks)} FAILED: {e}", flush=True)
            continue

        if isinstance(df.columns, pd.MultiIndex):
            for tkr in chunk:
                try:
                    s = df[tkr]["Close"].dropna()
                    if len(s) > 50:
                        closes[tkr] = s
                except (KeyError, AttributeError):
                    continue
        else:
            try:
                s = df["Close"].dropna()
                if len(s) > 50:
                    closes[chunk[0]] = s
            except (KeyError, AttributeError):
                pass

        if i % 5 == 0 or i == len(chunks):
            print(f"    chunk {i}/{len(chunks)}  cumulative={len(closes)}",
                  flush=True)
        time.sleep(1)  # gentle pacing

    out = pd.DataFrame(closes)
    print(f"  yfinance got {out.shape[1]}/{len(tickers)} tickers, "
          f"{out.shape[0]} bars", flush=True)
    return out


def fetch_prices(tickers: list[str], days: int = LOOKBACK_DAYS) -> pd.DataFrame:
    """Try Tradier first if TRADIER_TOKEN is set, fall back to yfinance for
    any tickers Tradier missed."""
    if TRADIER_TOKEN:
        out = fetch_prices_tradier(tickers, days)
        missing = [t for t in tickers if t not in out.columns]
        if missing and len(missing) < len(tickers):
            print(f"  filling {len(missing)} missing tickers via yfinance...",
                  flush=True)
            extra = fetch_prices_yfinance(missing, days)
            out = pd.concat([out, extra], axis=1)
        return out
    print("  (no TRADIER_TOKEN — using yfinance only)", flush=True)
    return fetch_prices_yfinance(tickers, days)


# ---------------------------------------------------------------------------
# Theme math
# ---------------------------------------------------------------------------

def theme_composite_returns(prices: pd.DataFrame, members: list[str]) -> pd.Series:
    """Equal-weighted daily return series for a basket of tickers."""
    valid = [m for m in members if m in prices.columns]
    if len(valid) < 2:
        return pd.Series(dtype=float)
    rets = prices[valid].pct_change()
    return rets.mean(axis=1)


def cumulative_return(daily_rets: pd.Series, window: int) -> float:
    """Cumulative return over the last `window` trading days."""
    if len(daily_rets) < window + 1:
        return np.nan
    tail = daily_rets.iloc[-window:]
    return float((1 + tail).prod() - 1)


def breadth(prices: pd.DataFrame, members: list[str], sma_window: int) -> float:
    """% of members with last close above their N-day SMA."""
    valid = [m for m in members if m in prices.columns]
    if not valid:
        return np.nan
    above = 0
    counted = 0
    for m in valid:
        s = prices[m].dropna()
        if len(s) < sma_window + 1:
            continue
        sma = s.iloc[-sma_window:].mean()
        if s.iloc[-1] > sma:
            above += 1
        counted += 1
    return (above / counted * 100) if counted else np.nan


def percentile_rank(values: dict[str, float]) -> dict[str, float]:
    """Returns {theme: 0-100 percentile} for the given metric across themes.
    NaN values are excluded from ranking and returned as NaN."""
    series = pd.Series(values).dropna()
    if len(series) < 2:
        return {k: np.nan for k in values}
    ranked = series.rank(pct=True) * 100
    out = {k: np.nan for k in values}
    out.update(ranked.to_dict())
    return out


# ---------------------------------------------------------------------------
# Main scoring pipeline
# ---------------------------------------------------------------------------

def build_theme_universe(master: dict, tv_sample_size: int = 30) -> dict[str, list[str]]:
    """Returns {theme_name: [members]} for both curated themes AND
    auto-generated themes from TradingView sectors. TV sector themes are
    capped at `tv_sample_size` members (sampled by market presence — we use
    the order they appear in the source CSV, which is roughly market-cap
    ranked from TradingView's export)."""
    themes: dict[str, list[str]] = dict(master["themes"])

    tv_buckets: dict[str, list[str]] = {}
    for sym, meta in master["tickers"].items():
        sec = meta.get("tv_sector")
        if sec:
            tv_buckets.setdefault(f"[TV] {sec}", []).append(sym)

    for name, members in tv_buckets.items():
        if len(members) >= 5:
            # Cap at sample size — first N from CSV order (cap-weighted-ish)
            themes[name] = members[:tv_sample_size]

    return themes


def member_daily_perf(prices: pd.DataFrame, members: list[str]) -> dict[str, float]:
    """Most-recent-day % change for each theme member, for sort-on-expand UI.
    Returns {ticker: pct} where pct = 100 * (last_close / prev_close - 1).
    NaN when not enough bars."""
    out: dict[str, float] = {}
    for m in members:
        if m not in prices.columns:
            continue
        s = prices[m].dropna()
        if len(s) < 2:
            continue
        prev = s.iloc[-2]
        last = s.iloc[-1]
        if prev <= 0:
            continue
        out[m] = round(float((last / prev - 1) * 100), 2)
    return out


def score_themes(prices: pd.DataFrame, themes: dict[str, list[str]],
                 spy_rets: pd.Series,
                 ticker_meta: dict[str, dict] | None = None) -> dict[str, dict]:
    """Compute raw metrics for each theme.

    `ticker_meta` (master_tickers.json's `tickers` block) lets us split each
    theme's membership into curated (hand-picked in CURATED_THEMES) and auto
    (heuristic-assigned via INDUSTRY_HINTS) so the frontend can flag them.
    """
    spy_rets_by_window = {w: cumulative_return(spy_rets, n)
                          for w, n in WINDOWS.items()}
    ticker_meta = ticker_meta or {}

    raw = {}
    for theme, members in themes.items():
        valid = [m for m in members if m in prices.columns]
        if len(valid) < 3:  # need at least 3 members for a meaningful basket
            continue
        # Split into curated vs heuristic-auto based on the global per-ticker
        # auto_theme flag (set in build_master_list during the auto-assign pass).
        # A ticker is either fully curated or fully auto across all its themes
        # (auto pass skips any ticker that already has a curated theme), so
        # this flag is unambiguous.
        curated_members = [m for m in valid if not ticker_meta.get(m, {}).get("auto_theme")]
        auto_members    = [m for m in valid if     ticker_meta.get(m, {}).get("auto_theme")]
        comp = theme_composite_returns(prices, valid)
        if comp.empty:
            continue

        # Composite price (cumulative for trend check)
        comp_price = (1 + comp.fillna(0)).cumprod()

        # 50-EMA trend on the composite
        ema50 = comp_price.ewm(span=50, adjust=False).mean()
        trend = 1 if comp_price.iloc[-1] > ema50.iloc[-1] else 0

        # RS = theme excess return vs SPY for each window
        rs_excess = {}
        for w, n in WINDOWS.items():
            theme_ret = cumulative_return(comp, n)
            spy_ret = spy_rets_by_window[w]
            if np.isnan(theme_ret) or np.isnan(spy_ret):
                rs_excess[w] = np.nan
            else:
                rs_excess[w] = (theme_ret - spy_ret) * 100  # percentage points

        raw[theme] = {
            "members": valid,
            "curated_members": curated_members,
            "auto_members": auto_members,
            "member_count": len(valid),
            "rs_excess": rs_excess,
            "breadth_50": breadth(prices, valid, 50),
            "breadth_200": breadth(prices, valid, 200),
            "trend": trend,
            "composite_price": float(comp_price.iloc[-1]),
            "member_perf": member_daily_perf(prices, valid),
        }
    return raw


def composite_scores(raw: dict[str, dict]) -> dict[str, dict]:
    """Apply percentile ranking and produce Daily/Weekly/Monthly composites."""
    # Percentile-rank RS for each window across all themes
    rs_rankings = {}
    for w in WINDOWS:
        rs_rankings[w] = percentile_rank({t: r["rs_excess"][w]
                                          for t, r in raw.items()})

    out = {}
    for theme, r in raw.items():
        rs_1w = rs_rankings["1W"].get(theme, np.nan)
        rs_1m = rs_rankings["1M"].get(theme, np.nan)
        rs_3m = rs_rankings["3M"].get(theme, np.nan)
        rs_6m = rs_rankings["6M"].get(theme, np.nan)
        b50 = r["breadth_50"] if not np.isnan(r["breadth_50"]) else 50.0
        b200 = r["breadth_200"] if not np.isnan(r["breadth_200"]) else 50.0
        trend = r["trend"] * 100

        def safe(*xs):
            return [x if not np.isnan(x) else 50.0 for x in xs]

        s_1w, s_1m, s_3m, s_6m = safe(rs_1w, rs_1m, rs_3m, rs_6m)

        daily = 0.50 * s_1w + 0.25 * s_1m + 0.15 * b50 + 0.10 * trend
        weekly = 0.20 * s_1w + 0.50 * s_1m + 0.15 * s_3m + 0.15 * b50
        monthly = 0.15 * s_1m + 0.40 * s_3m + 0.30 * s_6m + 0.15 * b200

        out[theme] = {
            "members": r["members"],
            "curated_members": r.get("curated_members", []),
            "auto_members": r.get("auto_members", []),
            "member_count": r["member_count"],
            "member_perf": r.get("member_perf", {}),
            "rs_excess_pct": {k: round(v, 2) if not np.isnan(v) else None
                              for k, v in r["rs_excess"].items()},
            "rs_rank": {
                "1W": round(rs_1w, 1) if not np.isnan(rs_1w) else None,
                "1M": round(rs_1m, 1) if not np.isnan(rs_1m) else None,
                "3M": round(rs_3m, 1) if not np.isnan(rs_3m) else None,
                "6M": round(rs_6m, 1) if not np.isnan(rs_6m) else None,
            },
            "breadth_50": round(b50, 1),
            "breadth_200": round(b200, 1),
            "trend_above_50ema": bool(r["trend"]),
            "scores": {
                "daily": round(daily, 1),
                "weekly": round(weekly, 1),
                "monthly": round(monthly, 1),
            },
        }
    return out


def append_history(theme_scores: dict[str, dict], asof: str) -> None:
    """Maintain a rolling history of just the composite scores for trend charts."""
    history: dict = {}
    if HISTORY_JSON.exists():
        try:
            history = json.loads(HISTORY_JSON.read_text())
        except json.JSONDecodeError:
            history = {}
    history.setdefault("dates", [])
    history.setdefault("daily", {})
    history.setdefault("weekly", {})
    history.setdefault("monthly", {})

    if asof in history["dates"]:
        # Re-running same day — replace
        idx = history["dates"].index(asof)
        for tf in ("daily", "weekly", "monthly"):
            for theme, data in theme_scores.items():
                arr = history[tf].setdefault(theme, [None] * len(history["dates"]))
                while len(arr) < len(history["dates"]):
                    arr.append(None)
                arr[idx] = data["scores"][tf]
    else:
        history["dates"].append(asof)
        for tf in ("daily", "weekly", "monthly"):
            # Extend existing series with None
            for theme in list(history[tf].keys()):
                history[tf][theme].append(None)
            for theme, data in theme_scores.items():
                arr = history[tf].setdefault(
                    theme, [None] * (len(history["dates"]) - 1))
                # Pad if theme is new mid-history
                while len(arr) < len(history["dates"]) - 1:
                    arr.append(None)
                if len(arr) < len(history["dates"]):
                    arr.append(data["scores"][tf])
                else:
                    arr[-1] = data["scores"][tf]

    # Cap history to last 180 days
    cap = 180
    if len(history["dates"]) > cap:
        cut = len(history["dates"]) - cap
        history["dates"] = history["dates"][cut:]
        for tf in ("daily", "weekly", "monthly"):
            for theme in history[tf]:
                history[tf][theme] = history[tf][theme][cut:]

    # Prune zombie themes — any series in history that's not in today's
    # theme_scores gets dropped. Without this, every theme rename or removal
    # leaves a stale series trailing forever (one None per day) that the
    # frontend either renders flat or lookup-errors on.
    #
    # CRITICAL: themes can be absent from one run for benign reasons —
    # yfinance dropping prices for all constituent tickers, master_tickers
    # not yet rebuilt, theme too small (<3 priced members threshold). The
    # original implementation deleted on a single-run absence, so a flaky
    # yfinance day permanently nuked legitimate themes from history. Now we
    # track consecutive absences in history["_absences"] and only prune
    # after PRUNE_THRESHOLD runs in a row — 7 runs ≈ 1 week of cron at
    # weekday + weekend cadence, enough to distinguish "deleted/renamed"
    # from "transient data hiccup".
    PRUNE_THRESHOLD = 7
    history.setdefault("_absences", {})
    current = set(theme_scores.keys())
    # Themes that exist anywhere in history (across all timeframes)
    all_history_themes: set[str] = set()
    for tf in ("daily", "weekly", "monthly"):
        all_history_themes.update(history[tf].keys())

    # Update absence counters
    for theme in all_history_themes:
        if theme in current:
            history["_absences"].pop(theme, None)
        else:
            history["_absences"][theme] = history["_absences"].get(theme, 0) + 1

    # Drop counters for themes that no longer exist in history at all
    # (already pruned previously)
    for theme in list(history["_absences"].keys()):
        if theme not in all_history_themes:
            del history["_absences"][theme]

    # Only prune themes that have been absent for >= PRUNE_THRESHOLD runs
    pruned: list[str] = []
    deferred: list[tuple[str, int]] = []
    for theme in list(all_history_themes):
        if theme in current:
            continue
        absences = history["_absences"].get(theme, 0)
        if absences >= PRUNE_THRESHOLD:
            for tf in ("daily", "weekly", "monthly"):
                history[tf].pop(theme, None)
            history["_absences"].pop(theme, None)
            if theme not in pruned:
                pruned.append(theme)
        else:
            deferred.append((theme, absences))

    if pruned:
        print(f"      pruned {len(pruned)} zombie theme(s) (absent >={PRUNE_THRESHOLD} runs): {sorted(pruned)}")
    if deferred:
        # Surface deferrals so a real-but-slow rename is visible in cron logs
        print(f"      {len(deferred)} theme(s) absent this run but kept (need {PRUNE_THRESHOLD} consecutive): "
              f"{sorted([f'{t}({n})' for t, n in deferred])[:10]}{'...' if len(deferred) > 10 else ''}")

    HISTORY_JSON.write_text(json.dumps(history))


def main():
    print(f"[1/4] loading {MASTER.name}...")
    master = json.loads(MASTER.read_text())
    themes = build_theme_universe(master)
    print(f"      {len(themes)} themes (curated + TV sectors)")

    # Collect every ticker we need to price
    needed = {BENCHMARK}
    for members in themes.values():
        needed.update(members)
    needed = sorted(needed)
    print(f"      {len(needed)} unique tickers to fetch")

    print(f"[2/4] downloading prices...")
    prices = fetch_prices(needed)
    if BENCHMARK not in prices.columns:
        print(f"FATAL: {BENCHMARK} not in fetched data. aborting.")
        sys.exit(1)
    # Coverage guard — refuse to commit a partial-data day. Prevents
    # rate-limited runs (e.g. yfinance throttle) from producing a half-empty
    # scores file that masquerades as a real snapshot.
    coverage = prices.shape[1] / max(1, len(needed))
    print(f"      coverage: {prices.shape[1]}/{len(needed)} tickers ({coverage:.1%})")
    if coverage < 0.85:
        print(f"FATAL: coverage {coverage:.1%} below 85% threshold; refusing to write degraded snapshot.")
        sys.exit(2)
    # Holiday/weekend guard — if the most recent bar isn't from today (or
    # we're running on a weekend), skip the commit. Otherwise we'd overwrite
    # Friday's snapshot with a duplicate "as_of" pointing at the same Friday.
    last_bar_date = prices.index[-1].date()
    today_utc = datetime.now(timezone.utc).date()
    if last_bar_date != today_utc:
        days_stale = (today_utc - last_bar_date).days
        # Allow up to 3 days stale (covers Friday → Monday weekend gap)
        if days_stale > 3:
            print(f"FATAL: most recent bar is {last_bar_date} ({days_stale} days stale); skipping.")
            sys.exit(3)
        print(f"      note: most recent bar is {last_bar_date} ({days_stale} day(s) ago — holiday/weekend?)")
    spy_rets = prices[BENCHMARK].pct_change()

    print(f"[3/4] scoring themes...")
    raw = score_themes(prices, themes, spy_rets, ticker_meta=master.get("tickers"))
    scored = composite_scores(raw)
    print(f"      scored {len(scored)} themes")

    asof = prices.index[-1].strftime("%Y-%m-%d")
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "as_of": asof,
        "benchmark": BENCHMARK,
        "windows": WINDOWS,
        "themes": scored,
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2))
    print(f"      wrote {OUT_JSON.name} ({OUT_JSON.stat().st_size//1024} KB)")

    print(f"[4/4] appending to history...")
    append_history(scored, asof)
    print(f"      history now has {len(json.loads(HISTORY_JSON.read_text())['dates'])} days")

    # Print top 10 by each timeframe to console for sanity check
    print("\n=== TOP 10 by DAILY score ===")
    top = sorted(scored.items(), key=lambda kv: kv[1]["scores"]["daily"], reverse=True)[:10]
    for t, d in top:
        print(f"  {d['scores']['daily']:5.1f}  {t:30s}  "
              f"({d['member_count']} members, RS_1W={d['rs_rank']['1W']})")

    print("\n=== TOP 10 by WEEKLY score ===")
    top = sorted(scored.items(), key=lambda kv: kv[1]["scores"]["weekly"], reverse=True)[:10]
    for t, d in top:
        print(f"  {d['scores']['weekly']:5.1f}  {t:30s}  "
              f"({d['member_count']} members, RS_1M={d['rs_rank']['1M']})")

    print("\n=== TOP 10 by MONTHLY score ===")
    top = sorted(scored.items(), key=lambda kv: kv[1]["scores"]["monthly"], reverse=True)[:10]
    for t, d in top:
        print(f"  {d['scores']['monthly']:5.1f}  {t:30s}  "
              f"({d['member_count']} members, RS_3M={d['rs_rank']['3M']}, "
              f"RS_6M={d['rs_rank']['6M']})")


if __name__ == "__main__":
    main()
