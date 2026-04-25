#!/usr/bin/env python3
"""
build_master_list.py
====================
Builds master_tickers.json from:
  1. alex_tickers.csv (TradingView export - universe + TV sector tag)
  2. Curated thematic baskets (hardcoded - the high-conviction groups)
  3. stockanalysis.com industry scrape (optional - granular industry tag)

Output schema (master_tickers.json):
{
  "generated_at": "...",
  "universe_size": 2400,
  "themes": {
    "Photonics":    ["LITE", "COHR", "AAOI", ...],
    "Memory":       ["MU", "WDC", "STX", ...],
    ...
  },
  "tickers": {
    "LITE": {
      "name": "Lumentum Holdings",
      "tv_sector": "Electronic technology",
      "industry": "Communication Equipment",
      "themes": ["Photonics", "AI Infrastructure"]
    },
    ...
  }
}

Run monthly. Output is checked into the repo and consumed by score_themes.py and themes.html.
"""

import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parents[1]
TICKERS_CSV = ROOT / "alex_tickers.csv"
OUT_JSON = ROOT / "industry" / "master_tickers.json"

# ---------------------------------------------------------------------------
# CURATED THEMATIC BASKETS
# ---------------------------------------------------------------------------
# These are the high-conviction, theme-level groupings that GICS doesn't capture
# cleanly. A ticker can belong to multiple themes (Photonics + AI Infra is common).
# Edit this dict directly to add/remove members.

CURATED_THEMES = {
    # --- AI / Compute stack ---
    "AI Infrastructure":   ["NVDA", "AVGO", "AMD", "MRVL", "SMCI", "DELL", "ANET",
                            "VRT", "ETN", "PWR", "GEV", "EME", "GNRC", "CEG"],
    "Photonics":           ["LITE", "COHR", "AAOI", "GLW", "IPGP", "LASR", "FN",
                            "MTSI", "POET", "ANET", "CIEN"],
    "Fiber Optics":        ["LITE", "COHR", "AAOI", "GLW", "CIEN", "INFN"],
    "Memory & Storage":    ["MU", "WDC", "STX", "SNDK", "NTAP"],
    "Semi Equipment":      ["AMAT", "LRCX", "TER", "KLAC", "ASML", "ENTG", "MKSI",
                            "ACLS", "ONTO", "FORM", "UCTT"],
    "Semiconductors":      ["NVDA", "AMD", "AVGO", "MRVL", "QCOM", "TXN", "INTC",
                            "MU", "ON", "MCHP", "ADI", "NXPI", "MPWR", "SMCI"],
    "Big Tech":            ["AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "META", "NVDA",
                            "TSLA"],

    # --- Defense / Aerospace ---
    "Defense":             ["KTOS", "AVAV", "PLTR", "HII", "LHX", "HWM", "NOC",
                            "RTX", "LMT", "GD", "TDG", "BA"],
    "Drones":              ["UMAC", "ONDS", "RDW", "RCAT", "AVAV", "KTOS", "AERT",
                            "DPRO", "EH", "ACHR", "JOBY"],
    "Space":               ["RKLB", "ASTS", "RDW", "MNTS", "PL", "IRDM", "VSAT",
                            "GSAT", "SATX"],

    # --- Energy / Power ---
    "Nuclear & Uranium":   ["UUUU", "CCJ", "DNN", "UEC", "NXE", "URG", "LEU",
                            "BWXT", "OKLO", "SMR", "CEG", "VST"],
    "AI Power":            ["VRT", "ETN", "PWR", "GEV", "EME", "GNRC", "CEG",
                            "VST", "NRG", "BE", "PLUG"],
    "Solar":               ["FSLR", "ENPH", "SEDG", "RUN", "NXT", "ARRY", "SHLS"],
    "Oil & Gas E&P":       ["XOM", "CVX", "COP", "EOG", "PXD", "OXY", "FANG",
                            "DVN", "MRO", "PR"],

    # --- Financials / Crypto ---
    "Crypto / Miners":     ["MARA", "RIOT", "CLSK", "HUT", "BITF", "CIFR", "WULF",
                            "IREN", "COIN", "MSTR", "GLXY"],
    "Fintech":             ["SQ", "PYPL", "SOFI", "AFRM", "HOOD", "COIN", "NU",
                            "BILL", "TOST", "MELI"],
    "Mega Banks":          ["JPM", "BAC", "WFC", "C", "GS", "MS", "USB"],

    # --- Other themes ---
    "Cybersecurity":       ["ZS", "CRWD", "PANW", "FTNT", "S", "CYBR", "NET",
                            "CHKP", "OKTA", "TENB"],
    "Quantum":             ["IONQ", "RGTI", "QBTS", "QUBT", "ARQQ", "IBM"],
    "Industrial / Picks":  ["CAT", "DE", "URI", "ETN", "EMR", "ROK"],
    "Travel & Leisure":    ["BKNG", "MAR", "ABNB", "RCL", "CCL", "NCLH", "DAL",
                            "UAL", "HLT", "EXPE"],
    "Retail / Consumer":   ["WMT", "COST", "TGT", "HD", "LOW", "DG", "DLTR"],

    # --- Recurring high-conviction picks ---
    "Top Recurring":       ["NVDA", "PLTR", "AMZN", "MSFT", "GOOGL", "META", "TSLA",
                            "AMD", "MRVL", "ZS", "SMCI", "MU"],
}

# ---------------------------------------------------------------------------
# stockanalysis.com industry scrape (optional layer)
# ---------------------------------------------------------------------------
# We grab the stockanalysis industry tag for each ticker as a secondary
# classification. They expose this on the per-ticker page in a stable spot.

UA = {"User-Agent": "Mozilla/5.0 (compatible; theme-builder/1.0)"}

def fetch_industry_tag(ticker: str, session: requests.Session) -> str | None:
    """Scrape stockanalysis.com for granular industry. Returns None on failure."""
    url = f"https://stockanalysis.com/stocks/{ticker.lower()}/"
    try:
        r = session.get(url, headers=UA, timeout=8)
        if r.status_code != 200:
            return None
        # Industry shows up as: <td>Industry</td><td><a ...>Foo Bar</a></td>
        m = re.search(
            r"Industry[^<]*</td>\s*<td[^>]*>\s*<a[^>]*>([^<]+)</a>",
            r.text,
            re.IGNORECASE,
        )
        return m.group(1).strip() if m else None
    except Exception:
        return None


def load_universe() -> dict[str, dict]:
    """Read alex_tickers.csv into {ticker: {name, tv_sector}}."""
    out = {}
    with open(TICKERS_CSV, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            sym = (row.get("Symbol") or "").strip().upper()
            if not sym or "/" in sym or "." in sym:
                continue
            out[sym] = {
                "name": (row.get("Description") or "").strip(),
                "tv_sector": (row.get("Sector") or "").strip(),
                "industry": None,
                "themes": [],
            }
    return out


def apply_curated_themes(
    tickers: dict[str, dict],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Tag tickers with curated theme membership. STRICT mode: only tickers
    present in the universe (alex_tickers.csv) are kept in any theme.

    Returns (themes_in_universe, missing_per_theme) where missing_per_theme
    records the curated members that were dropped because they aren't in the
    user's universe — written to missing_from_universe.txt for review.
    """
    themes: dict[str, list[str]] = {}
    missing: dict[str, list[str]] = {}
    for theme, members in CURATED_THEMES.items():
        kept, dropped = [], []
        for sym in members:
            if sym in tickers:
                tickers[sym]["themes"].append(theme)
                kept.append(sym)
            else:
                dropped.append(sym)
        themes[theme] = kept
        if dropped:
            missing[theme] = dropped
    return themes, missing


def write_missing_report(missing: dict[str, list[str]]) -> None:
    """Write industry/missing_from_universe.txt — curated theme members that
    were dropped because they aren't in alex_tickers.csv. Lets the user audit
    and decide whether to add any of them to the universe."""
    out_path = ROOT / "industry" / "missing_from_universe.txt"
    lines = [
        "Tickers referenced by curated themes in build_master_list.py but NOT",
        "present in alex_tickers.csv. They were filtered out of the INDUSTRY tab.",
        "Add to alex_tickers.csv if you want them scored.",
        f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "",
    ]
    if not missing:
        lines.append("(none — every curated member is in your universe)")
    else:
        total = sum(len(v) for v in missing.values())
        lines.append(f"{total} ticker-slot(s) across {len(missing)} theme(s):")
        lines.append("")
        for theme in sorted(missing):
            lines.append(f"{theme}:")
            for sym in missing[theme]:
                lines.append(f"  - {sym}")
            lines.append("")
    out_path.write_text("\n".join(lines))
    print(f"      wrote {out_path.name}")


def enrich_with_industry_tags(tickers: dict[str, dict], limit: int | None = None,
                              sleep_s: float = 0.25) -> None:
    """OPTIONAL: Hit stockanalysis.com to get a granular industry tag.

    Slow (~0.25s/ticker, so ~10 min for 2,400 tickers). Skip with limit=0
    on first run; run later as a one-time enrichment pass.
    """
    sess = requests.Session()
    syms = list(tickers.keys())
    if limit is not None:
        syms = syms[:limit]
    total = len(syms)
    for i, sym in enumerate(syms, 1):
        if tickers[sym].get("industry"):
            continue
        ind = fetch_industry_tag(sym, sess)
        if ind:
            tickers[sym]["industry"] = ind
        if i % 50 == 0:
            print(f"  [industry tags] {i}/{total}  last={sym}->{ind}", flush=True)
        time.sleep(sleep_s)


def main(industry_scrape_limit: int | None = 0) -> None:
    """industry_scrape_limit=0 skips the slow scrape (default). Pass None
    to scrape all, or an integer for a sample run."""
    print(f"[1/3] loading universe from {TICKERS_CSV.name}...")
    tickers = load_universe()
    print(f"      {len(tickers)} tickers loaded")

    print(f"[2/3] applying {len(CURATED_THEMES)} curated themes (strict to universe)...")
    themes, missing = apply_curated_themes(tickers)
    tagged = sum(1 for t in tickers.values() if t.get("themes"))
    dropped_total = sum(len(v) for v in missing.values())
    print(f"      {tagged} tickers tagged with at least one theme")
    print(f"      {dropped_total} curated ticker-slot(s) dropped (not in alex_tickers.csv)")
    write_missing_report(missing)

    if industry_scrape_limit != 0:
        print(f"[3/3] scraping stockanalysis.com industry tags "
              f"(limit={industry_scrape_limit})...")
        enrich_with_industry_tags(tickers, limit=industry_scrape_limit)
    else:
        print("[3/3] SKIPPING industry scrape (use --enrich to enable)")

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "universe_size": len(tickers),
        "theme_count": len(themes),
        "themes": themes,
        "tickers": tickers,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, indent=2))
    print(f"\n✓ wrote {OUT_JSON} ({OUT_JSON.stat().st_size//1024} KB)")


if __name__ == "__main__":
    # CLI: python build_master_list.py [--enrich [N]]
    enrich_arg = 0
    if "--enrich" in sys.argv:
        idx = sys.argv.index("--enrich")
        enrich_arg = None
        if idx + 1 < len(sys.argv) and sys.argv[idx + 1].isdigit():
            enrich_arg = int(sys.argv[idx + 1])
    main(industry_scrape_limit=enrich_arg)
