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
import html
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

# Make sibling industry/ scripts importable when run from the repo root
# (so we can reuse audit_unassigned's heuristic suggester for auto-assigning
# unassigned tickers to themes after the curated pass).
sys.path.insert(0, str(Path(__file__).resolve().parent))

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

    # --- Financials (granular) ---
    "Regional Banks":      ["KEY", "RF", "CFG", "FITB", "MTB", "HBAN", "CMA", "ZION",
                            "PNC", "TFC", "FHN", "WAL", "CFR", "PB", "BPOP"],
    "Custody Banks":       ["BK", "STT", "NTRS"],
    "Asset Managers":      ["BLK", "BX", "KKR", "APO", "ARES", "BAM", "OWL", "TROW",
                            "BEN", "IVZ", "AMG", "SEIC"],
    "P&C Insurance":       ["TRV", "CB", "ALL", "PGR", "AIG", "HIG", "WRB", "L",
                            "CINF", "ERIE", "RLI", "AFG"],
    "Life Insurance":      ["MET", "PRU", "AFL", "LNC", "PFG", "GL", "EQH", "VOYA"],
    "Insurance Brokers":   ["AON", "MMC", "AJG", "WTW", "BRO", "RYAN"],
    "Reinsurance":         ["RNR", "EG", "ACGL", "RGA"],
    "Specialty Finance":   ["ALLY", "DFS", "SYF", "COF", "AXP", "NAVI", "OMF",
                            "BX", "ARES"],
    "Exchanges":           ["ICE", "CME", "NDAQ", "CBOE", "MKTX", "TW"],

    # --- REITs (by sub-type) ---
    "Tower REITs":         ["AMT", "CCI", "SBAC"],
    "Data Center REITs":   ["DLR", "EQIX"],
    "Industrial REITs":    ["PLD", "REXR", "EGP", "FR", "STAG", "TRNO", "EXR"],
    "Self-Storage REITs":  ["PSA", "EXR", "CUBE", "NSA"],
    "Residential REITs":   ["MAA", "AVB", "EQR", "ESS", "UDR", "CPT", "INVH",
                            "AMH", "ELS", "SUI"],
    "Retail REITs":        ["O", "SPG", "REG", "FRT", "KIM", "BRX", "MAC", "AKR",
                            "NNN", "ADC"],
    "Office REITs":        ["BXP", "VNO", "KRC", "CUZ", "HIW", "DEI"],
    "Hotel REITs":         ["HST", "PK", "RHP", "APLE", "SHO", "DRH"],
    "Mortgage REITs":      ["AGNC", "NLY", "STWD", "ABR", "BXMT", "RITM", "DX",
                            "NYMT", "TWO"],

    # --- Auto / Mobility ---
    "Auto OEMs":           ["TSLA", "F", "GM", "RIVN", "LCID", "STLA", "TM", "HMC"],
    "Auto Suppliers":      ["APTV", "BWA", "MGA", "LEA", "DAN", "MOD", "GTX",
                            "ALV", "PHIN", "DORM", "STRT"],
    "Auto Dealers":        ["AN", "KMX", "PAG", "GPI", "ABG", "LAD", "SAH"],
    "Auto Parts Retail":   ["AZO", "ORLY", "AAP", "MNRO"],
    "EV Charging":         ["CHPT", "BLNK", "EVGO", "WBX"],

    # --- Consumer / Restaurants / Apparel ---
    "Restaurants - QSR":   ["MCD", "CMG", "YUM", "QSR", "DPZ", "WING", "SHAK",
                            "PZZA", "JACK", "WEN", "DNUT", "PLAY", "TXRH"],
    "Restaurants - Casual":["DRI", "EAT", "BLMN", "BJRI", "CAKE", "CHEF", "BROS"],
    "Coffee":              ["SBUX", "DNUT", "BROS", "FARM"],
    "Athletic Apparel":    ["NKE", "LULU", "UA", "UAA", "ONON", "DECK", "SKX",
                            "BIRK", "CROX", "VFC", "COLM", "GES"],
    "Luxury / Fashion":    ["TPR", "RL", "CPRI", "TJX", "ROST", "BURL", "ANF",
                            "AEO", "URBN", "LULU"],
    "Sporting Goods":      ["DKS", "ASO", "HIBB", "BGFV"],

    # --- Travel sub-segments ---
    "Airlines":            ["DAL", "UAL", "AAL", "LUV", "ALK", "SAVE", "JBLU",
                            "ALGT", "HA", "SKYW", "MESA"],
    "Cruise Lines":        ["CCL", "RCL", "NCLH", "VIK"],
    "Hotels & Lodging":    ["MAR", "HLT", "H", "IHG", "CHH", "HGV", "WH", "PLYA"],
    "Online Travel":       ["BKNG", "EXPE", "ABNB", "TRIP", "TRVG"],
    "Casinos":             ["LVS", "WYNN", "MGM", "CZR", "BYD", "RRR", "PENN",
                            "MCRI", "FLL", "GDEN"],
    "Online Gambling":     ["DKNG", "FLUT", "BETZ", "RSI", "GAN", "PLTK"],

    # --- Transports ---
    "Class I Rails":       ["UNP", "NSC", "CSX", "CNI", "CP"],
    "Trucking / LTL":      ["ODFL", "JBHT", "KNX", "XPO", "WERN", "CHRW", "ARCB",
                            "LSTR", "SNDR", "HTLD", "MRTN"],
    "Logistics & Parcels": ["FDX", "UPS", "EXPD", "GXO", "ZTO", "FWRD"],
    "Marine Shipping":     ["ZIM", "MATX", "KEX", "SBLK", "GOGL", "DAC", "GSL",
                            "CMRE"],

    # --- Industrial / Materials ---
    "Building Products":   ["TT", "WSO", "LII", "JCI", "MAS", "AOS", "FBIN",
                            "PNR", "WMS", "CSL", "AZEK", "TREX"],
    "Homebuilders":        ["DHI", "LEN", "NVR", "PHM", "TOL", "KBH", "MTH",
                            "TPH", "MHO", "BZH", "GRBK", "CCS"],
    "Heavy Machinery":     ["CAT", "DE", "AGCO", "TEX", "OSK", "PCAR"],
    "Industrial Auto":     ["ROK", "EMR", "ETN", "HUBB", "WAB", "DOV", "FLS",
                            "GGG", "WTS"],
    "Aerospace OEM":       ["BA", "TDG", "HEI", "TXT", "GE", "RTX", "HXL", "SPR"],
    "Cement & Aggregates": ["VMC", "MLM", "EXP", "USCR", "SUM", "CX", "EAF"],
    "Steel":               ["NUE", "STLD", "X", "CLF", "MT", "TX", "ATI",
                            "RS", "CMC", "WOR"],
    "Copper / Base Metal": ["FCX", "SCCO", "TECK", "BHP", "RIO", "VALE", "ERO",
                            "HBM", "TRQ"],
    "Gold Miners":         ["NEM", "AEM", "GOLD", "AU", "KGC", "AGI", "PAAS",
                            "WPM", "FNV", "SSRM", "EGO", "NGD", "BTG"],
    "Lithium":             ["ALB", "SQM", "LAC", "LTHM", "PLL", "SGML"],
    "Specialty Chemicals": ["LIN", "APD", "ECL", "SHW", "PPG", "RPM", "ALB",
                            "DD", "FUL", "CE", "ESI"],
    "Commodity Chem":      ["DOW", "LYB", "EMN", "OLN", "WLK", "HUN", "TROX"],
    "Packaging":           ["PKG", "IP", "AMCR", "SEE", "BERY", "WRK", "SLGN",
                            "OI", "BALL", "SON"],
    "Ag Inputs":           ["CTVA", "MOS", "CF", "NTR", "FMC", "SMG"],

    # --- Energy adjacencies ---
    "Pipelines / Midstream":["ENB", "ET", "EPD", "MPLX", "WMB", "OKE", "KMI",
                             "TRGP", "PAA", "WES", "DTM", "PAGP", "ENLC"],
    "Refiners":            ["MPC", "VLO", "PSX", "DK", "PBF", "HF", "DINO"],
    "Oilfield Services":   ["SLB", "HAL", "BKR", "FTI", "CHX", "WFRD", "NOV",
                            "PUMP", "RIG", "OII", "TS"],

    # --- Communications / Media ---
    "Telecom":             ["T", "VZ", "TMUS", "LUMN"],
    "Cable":               ["CMCSA", "CHTR", "ATUS", "WBD"],
    "Streaming / Media":   ["NFLX", "DIS", "WBD", "PARA", "ROKU", "SIRI", "FUBO",
                            "LYV", "WMG", "SPOT"],
    "Video Games":         ["TTWO", "EA", "RBLX", "U", "PLTK", "GLBE"],
    "AdTech":              ["TTD", "PUBM", "MGNI", "DV", "APPS", "ZETA", "ROKU"],
    "Tobacco":             ["MO", "PM", "BTI"],

    # --- Consumer staples (granular) ---
    "Beverages":           ["KO", "PEP", "KDP", "MNST", "CELH", "STZ", "BUD",
                            "TAP", "DEO", "SAM", "FIZZ", "PRMW", "COCO"],
    "Packaged Food":       ["GIS", "K", "MDLZ", "CAG", "HRL", "CPB", "SJM",
                            "MKC", "INGR", "POST", "TR", "FLO", "LANC"],
    "Grocery":             ["KR", "ACI", "SFM", "GO"],
    "Personal Care":       ["PG", "CL", "CHD", "EL", "KMB", "CLX", "ENR",
                            "REYN", "SPB"],

    # --- Tech / Software (granular) ---
    "Enterprise SaaS":     ["CRM", "NOW", "ADBE", "INTU", "WDAY", "ANSS", "TYL",
                            "SAP", "ORCL", "HUBS", "BSY", "TEAM", "PCTY"],
    "Cloud / CDN":         ["NET", "FSLY", "AKAM", "DNB", "CLDR"],
    "Data / DevOps":       ["SNOW", "DDOG", "MDB", "ESTC", "GTLB", "DT", "CFLT",
                            "S", "PATH", "AI", "BSY", "PD"],
    "Payments":            ["V", "MA", "PYPL", "FIS", "FI", "JKHY", "GPN", "WU",
                            "RELY", "EBC", "PAYO", "FLYW"],
    "BNPL / Consumer Lending":["AFRM", "UPST", "PAGS", "STNE", "OPRT", "ENVA"],
    "E-Commerce":          ["AMZN", "SHOP", "MELI", "EBAY", "ETSY", "W", "CHWY",
                            "JD", "BABA", "PDD", "CPNG", "GLBE", "RVLV", "SE"],

    # --- Other niches ---
    "China ADRs":          ["BABA", "PDD", "JD", "BIDU", "NTES", "TCOM", "BILI",
                            "TME", "ZTO", "VIPS", "IQ", "WB", "BEKE", "LI",
                            "NIO", "XPEV"],
    "LATAM":               ["MELI", "PAGS", "STNE", "NU", "BBD", "ITUB", "VALE",
                            "PBR", "ABEV", "SBS"],
    "Cannabis":            ["TLRY", "CGC", "SNDL", "ACB", "OGI", "CRON"],
    "Theme Parks":         ["SIX", "FUN", "DIS"],
}

# ---------------------------------------------------------------------------
# stockanalysis.com industry scrape (optional layer)
# ---------------------------------------------------------------------------
# We grab the stockanalysis industry tag for each ticker as a secondary
# classification. They expose this on the per-ticker page in a stable spot.

UA = {"User-Agent": "Mozilla/5.0 (compatible; theme-builder/1.0)"}

def fetch_industry_tag(ticker: str, session: requests.Session) -> str | None:
    """Scrape stockanalysis.com for granular industry. Returns None on failure.

    Their HTML rev'd in 2025+: industry now lives in two stable places:
      1. A link: <a href="...industry/<slug>/" ...>Industry Name</a>
      2. An inline JS data tuple: Industry",v:"Industry Name",u:"stocks/industry/..."

    We try the link first (most stable), fall back to the JS blob.
    """
    url = f"https://stockanalysis.com/stocks/{ticker.lower()}/"
    try:
        r = session.get(url, headers=UA, timeout=8)
        if r.status_code != 200:
            return None
        # Pattern 1: anchor whose href points into /industry/SLUG/
        m = re.search(
            r'href="[^"]*industry/[^"/]+/"[^>]*>([^<]+)</a>',
            r.text,
        )
        if m:
            name = html.unescape(m.group(1)).strip()
            # Skip the literal "By Industry" navigation link
            if name and name.lower() != "by industry":
                return name
        # Pattern 2: JS data tuple
        m = re.search(r'Industry"\s*,\s*v\s*:\s*"([^"]+)"', r.text)
        return html.unescape(m.group(1)).strip() if m else None
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

    # Preserve previously-fetched industry tags from the existing
    # master_tickers.json so --enrich only hits stockanalysis.com for
    # tickers that don't have a tag yet (e.g. ones newly added to the CSV).
    if OUT_JSON.exists():
        try:
            prior = json.loads(OUT_JSON.read_text())
            carried = 0
            for sym, meta in (prior.get("tickers") or {}).items():
                ind = meta.get("industry")
                if ind and sym in tickers:
                    tickers[sym]["industry"] = ind
                    carried += 1
            if carried:
                print(f"      carried {carried} industry tag(s) from prior master_tickers.json")
        except (json.JSONDecodeError, OSError):
            pass

    print(f"[2/3] applying {len(CURATED_THEMES)} curated themes (strict to universe)...")
    themes, missing = apply_curated_themes(tickers)
    tagged = sum(1 for t in tickers.values() if t.get("themes"))
    dropped_total = sum(len(v) for v in missing.values())
    print(f"      {tagged} tickers tagged with at least one theme")
    print(f"      {dropped_total} curated ticker-slot(s) dropped (not in alex_tickers.csv)")
    write_missing_report(missing)

    # Auto-assignment pass: for every ticker NOT placed by a curated theme,
    # use audit_unassigned's heuristic (TV sector + stockanalysis.com industry
    # tag) to suggest a theme and add the ticker as a theme member. Healthcare
    # is intentionally skipped (per user preference: no healthcare in themes).
    # Tickers with no clear suggestion (mostly ETFs / miscellaneous) stay
    # unassigned and surface in unassigned_tickers.md for review.
    try:
        import audit_unassigned
    except ImportError:
        print("      WARN: could not import audit_unassigned; skipping auto-assignment")
        audit_unassigned = None
    if audit_unassigned is not None:
        added_total = 0
        added_per_theme: dict[str, int] = {}
        for sym, meta in tickers.items():
            if meta.get("themes"):       # already curated → leave alone
                continue
            if audit_unassigned.is_healthcare(meta):
                continue
            suggestion = audit_unassigned.suggest_theme(meta)
            if not suggestion:
                continue
            themes.setdefault(suggestion, []).append(sym)
            meta["themes"].append(suggestion)
            meta["auto_theme"] = True   # mark as heuristic so the frontend can flag it
            added_total += 1
            added_per_theme[suggestion] = added_per_theme.get(suggestion, 0) + 1
        tagged = sum(1 for t in tickers.values() if t.get("themes"))
        print(f"      auto-assigned {added_total} additional tickers to existing themes "
              f"(via INDUSTRY_HINTS / SECTOR_HINTS heuristic)")
        print(f"      {tagged} tickers now have at least one theme")
        for theme, n in sorted(added_per_theme.items(), key=lambda kv: -kv[1])[:15]:
            curated_n = len(CURATED_THEMES.get(theme, []))
            print(f"        +{n:4d}  {theme}  (was {curated_n} curated)")

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
