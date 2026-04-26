"""
Smoke test for industry/theme_scores.json
==========================================

Run after score_themes.py writes a fresh snapshot but BEFORE git commit
(in the GH Actions cron workflow). Goal is to catch upstream regressions
that the pipeline doesn't notice — yfinance schema changes, all-NaN output,
SPY missing, theme count collapsing, score distribution flattening.

Each assertion is conservative: a normal scoring run easily clears every
threshold. The test should never fail when the data is healthy. If it
fails, the cron workflow aborts the commit so the previous (good)
snapshot stays in place rather than being overwritten with garbage.

Run locally:
    cd industry/
    python3 -m pytest test_theme_scores.py -v

CI integration: see .github/workflows/score_themes.yml — runs between
"Run scoring engine" and "Commit refreshed scores".
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
THEME_SCORES_PATH = REPO_ROOT / "industry" / "theme_scores.json"

# Conservative thresholds. The current snapshot has 119 themes with daily
# scores; setting the floor at 50 leaves headroom for theme-list pruning
# without making the test trip on a normal pipeline change.
MIN_THEMES = 50
# Fraction of themes that must have a non-null daily score. yfinance partial
# failures are routine; we tolerate up to 30% missing. Below that, the
# pipeline is broken or rate-limited and the snapshot shouldn't ship.
MIN_NONNULL_DAILY_FRACTION = 0.70
# Score distribution shouldn't be degenerate. If every theme scores the
# same value, percentile ranking is broken and the output is useless.
MIN_DAILY_STDDEV = 5.0
# Max age (in calendar days) of the `as_of` field vs today. Cron runs M-F,
# so up to 5 days old after a long weekend + holiday is fine; >7 means the
# pipeline silently stopped writing fresh data.
MAX_AS_OF_AGE_DAYS = 7


@pytest.fixture(scope="module")
def snapshot() -> dict:
    if not THEME_SCORES_PATH.exists():
        pytest.fail(f"theme_scores.json not found at {THEME_SCORES_PATH}")
    with THEME_SCORES_PATH.open() as f:
        return json.load(f)


def test_top_level_shape(snapshot: dict) -> None:
    """The output JSON has the expected top-level keys."""
    required = {"generated_at", "as_of", "benchmark", "windows", "themes"}
    missing = required - set(snapshot.keys())
    assert not missing, f"missing top-level keys: {missing}"


def test_benchmark_is_spy(snapshot: dict) -> None:
    """SPY is the benchmark — change requires updating the rest of the
    pipeline + scanner together."""
    assert snapshot["benchmark"] == "SPY"


def test_as_of_is_recent(snapshot: dict) -> None:
    """as_of must be a parseable date and not stale."""
    as_of = snapshot["as_of"]
    parsed = dt.datetime.strptime(as_of, "%Y-%m-%d").date()
    age = (dt.date.today() - parsed).days
    assert -1 <= age <= MAX_AS_OF_AGE_DAYS, (
        f"as_of date {as_of} is {age} days old (max {MAX_AS_OF_AGE_DAYS}) — "
        "pipeline may have stopped writing fresh data"
    )


def test_theme_count(snapshot: dict) -> None:
    """At least MIN_THEMES themes were scored."""
    n = len(snapshot["themes"])
    assert n >= MIN_THEMES, f"only {n} themes scored (expected >= {MIN_THEMES})"


def test_theme_shape(snapshot: dict) -> None:
    """Every theme has the required nested structure."""
    required = {"members", "scores", "rs_excess_pct"}
    score_keys = {"daily", "weekly", "monthly"}
    for name, theme in snapshot["themes"].items():
        missing = required - set(theme.keys())
        assert not missing, f"theme {name!r} missing keys: {missing}"
        sk_missing = score_keys - set(theme["scores"].keys())
        assert not sk_missing, f"theme {name!r} scores missing: {sk_missing}"


def test_daily_score_coverage(snapshot: dict) -> None:
    """At least MIN_NONNULL_DAILY_FRACTION of themes have a non-null
    daily score. Below that, yfinance is failing too many tickers and
    the snapshot is unreliable."""
    themes = snapshot["themes"]
    total = len(themes)
    non_null = sum(1 for t in themes.values()
                   if t["scores"].get("daily") is not None)
    fraction = non_null / total if total else 0
    assert fraction >= MIN_NONNULL_DAILY_FRACTION, (
        f"only {non_null}/{total} themes have non-null daily scores "
        f"({fraction:.1%}) — required >= {MIN_NONNULL_DAILY_FRACTION:.0%}"
    )


def test_daily_score_range(snapshot: dict) -> None:
    """Non-null daily scores must be in [0, 100]."""
    bad = []
    for name, t in snapshot["themes"].items():
        s = t["scores"].get("daily")
        if s is None:
            continue
        if not (0 <= float(s) <= 100):
            bad.append((name, s))
    assert not bad, f"themes with out-of-range daily score: {bad[:5]}"


def test_daily_score_distribution(snapshot: dict) -> None:
    """Score distribution isn't degenerate. If every theme scores the same
    value (or all 0, or all NaN-rounded-to-0), percentile ranking is broken
    and downstream consumers get noise."""
    scores = [
        float(t["scores"]["daily"])
        for t in snapshot["themes"].values()
        if t["scores"].get("daily") is not None
    ]
    assert scores, "no non-null daily scores to compute distribution"
    mean = sum(scores) / len(scores)
    var = sum((s - mean) ** 2 for s in scores) / len(scores)
    stddev = var ** 0.5
    assert stddev >= MIN_DAILY_STDDEV, (
        f"daily score stddev = {stddev:.2f} (min {MIN_DAILY_STDDEV}) — "
        "distribution is degenerate; percentile ranking won't discriminate"
    )


def test_no_all_zero_scores(snapshot: dict) -> None:
    """Sanity: at least one theme has a non-zero daily score. Catches the
    extreme failure mode where every score is the floor (zero)."""
    has_nonzero = any(
        (t["scores"].get("daily") or 0) > 0
        for t in snapshot["themes"].values()
    )
    assert has_nonzero, "every daily score is zero or null — pipeline produced no signal"


def test_member_count_non_empty(snapshot: dict) -> None:
    """Every theme has at least one member. A theme with zero members
    indicates a broken alex_tickers.csv intersection or a curated theme
    with all-removed tickers."""
    empty = [name for name, t in snapshot["themes"].items() if not t.get("members")]
    assert not empty, f"themes with zero members: {empty[:5]}"
