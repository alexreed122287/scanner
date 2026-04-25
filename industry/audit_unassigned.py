#!/usr/bin/env python3
"""
audit_unassigned.py
===================
Lists every ticker in alex_tickers.csv that has NO curated theme assigned,
with a suggested theme based on its TradingView sector / stockanalysis industry
tag (when available).

Output: industry/unassigned_tickers.md  (human review)
        industry/unassigned_tickers.json (frontend consumption)

Run after build_master_list.py. Pure read — does not modify anything else.
"""

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "industry" / "master_tickers.json"
OUT_MD = ROOT / "industry" / "unassigned_tickers.md"
OUT_JSON = ROOT / "industry" / "unassigned_tickers.json"

# Heuristic mapping from TV sector / industry substrings to a curated theme.
# Order matters: first match wins. Themes here must exist in build_master_list's
# CURATED_THEMES; if a suggested theme has been removed/renamed there, it just
# becomes a hint for the reviewer.
SECTOR_HINTS: list[tuple[str, str]] = [
    ("electronic technology",      "Semiconductors"),
    ("electronic production",      "Semi Equipment"),
    ("technology services",        "Big Tech"),
    ("commercial services",        "Industrial / Picks"),
    ("communications",             "Big Tech"),
    ("producer manufacturing",     "Industrial / Picks"),
    ("industrial services",        "Industrial / Picks"),
    ("transportation",             "Travel & Leisure"),
    ("consumer durables",          "Retail / Consumer"),
    ("consumer non-durables",      "Retail / Consumer"),
    ("consumer services",          "Travel & Leisure"),
    ("retail trade",               "Retail / Consumer"),
    ("distribution services",      "Retail / Consumer"),
    ("finance",                    "Mega Banks"),
    ("utilities",                  "AI Power"),
    ("energy minerals",            "Oil & Gas E&P"),
    ("non-energy minerals",        "Industrial / Picks"),
    ("process industries",         "Industrial / Picks"),
]

INDUSTRY_HINTS: list[tuple[str, str]] = [
    ("semiconductor",              "Semiconductors"),
    ("uranium",                    "Nuclear & Uranium"),
    ("nuclear",                    "Nuclear & Uranium"),
    ("solar",                      "Solar"),
    ("oil",                        "Oil & Gas E&P"),
    ("gas",                        "Oil & Gas E&P"),
    ("aerospace",                  "Defense"),
    ("defense",                    "Defense"),
    ("bank",                       "Mega Banks"),
    ("software",                   "Big Tech"),
    ("internet",                   "Big Tech"),
    ("crypto",                     "Crypto / Miners"),
    ("blockchain",                 "Crypto / Miners"),
    ("airline",                    "Travel & Leisure"),
    ("hotel",                      "Travel & Leisure"),
    ("retail",                     "Retail / Consumer"),
]


# Healthcare is intentionally excluded from theme assignment per user preference.
# These tickers stay unassigned and are NOT listed in the audit (no review needed).
HEALTHCARE_SECTOR_TOKENS = ("health technology", "health services")
HEALTHCARE_INDUSTRY_TOKENS = ("biotech", "pharma", "drug", "medical", "hospital",
                              "healthcare")


def is_healthcare(meta: dict) -> bool:
    sec = (meta.get("tv_sector") or "").lower()
    ind = (meta.get("industry") or "").lower()
    if any(tok in sec for tok in HEALTHCARE_SECTOR_TOKENS):
        return True
    if any(tok in ind for tok in HEALTHCARE_INDUSTRY_TOKENS):
        return True
    return False


def suggest_theme(meta: dict) -> str | None:
    sec = (meta.get("tv_sector") or "").lower()
    ind = (meta.get("industry") or "").lower()
    for needle, theme in INDUSTRY_HINTS:
        if needle in ind:
            return theme
    for needle, theme in SECTOR_HINTS:
        if needle in sec:
            return theme
    return None


def main() -> None:
    if not MASTER.exists():
        raise SystemExit(f"missing {MASTER}; run build_master_list.py first")

    master = json.loads(MASTER.read_text())
    tickers = master.get("tickers", {})

    unassigned: list[tuple[str, dict, str | None]] = []
    healthcare_skipped = 0
    for sym, meta in tickers.items():
        if meta.get("themes"):
            continue
        if is_healthcare(meta):
            healthcare_skipped += 1
            continue
        suggestion = suggest_theme(meta)
        unassigned.append((sym, meta, suggestion))

    unassigned.sort(key=lambda row: ((row[2] or "ZZZ"), row[0]))

    by_sugg: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for sym, meta, sugg in unassigned:
        by_sugg[sugg or "(no suggestion)"].append((sym, meta))

    md = [
        "# Unassigned Tickers Audit",
        "",
        f"_Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}_",
        "",
        f"**{len(unassigned)} of {len(tickers)} tickers** in `alex_tickers.csv` "
        "have no curated theme (excluding healthcare).",
        "",
        f"_{healthcare_skipped} healthcare tickers were intentionally skipped "
        "(per user preference: no healthcare in themes)._",
        "",
        "Suggestions are heuristic (based on TradingView sector / stockanalysis "
        "industry tag). Edit `industry/build_master_list.py` to add them to a "
        "theme — then re-run `python3 industry/build_master_list.py && "
        "python3 industry/score_themes.py`.",
        "",
    ]
    for sugg in sorted(by_sugg):
        rows = by_sugg[sugg]
        md.append(f"## → {sugg} ({len(rows)})")
        md.append("")
        md.append("| Ticker | Name | TV Sector | Industry |")
        md.append("|---|---|---|---|")
        for sym, meta in rows:
            name = (meta.get("name") or "").replace("|", "\\|")
            sec = meta.get("tv_sector") or ""
            ind = meta.get("industry") or ""
            md.append(f"| `{sym}` | {name} | {sec} | {ind} |")
        md.append("")

    OUT_MD.write_text("\n".join(md))
    print(f"wrote {OUT_MD.relative_to(ROOT)}  ({len(unassigned)} tickers)")

    OUT_JSON.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "unassigned_count": len(unassigned),
        "healthcare_skipped": healthcare_skipped,
        "universe_size": len(tickers),
        "by_suggestion": {
            sugg: [
                {"ticker": s, "name": m.get("name") or "",
                 "tv_sector": m.get("tv_sector") or "",
                 "industry": m.get("industry") or ""}
                for s, m in rows
            ]
            for sugg, rows in by_sugg.items()
        },
    }, indent=2))
    print(f"wrote {OUT_JSON.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
