#!/usr/bin/env python3
"""
strategy_report.py
==================
Render a clean PDF describing Option Panda's strategies and the paper-backtest
options book, including performance tables computed live from paper_ledger.json.

Two kinds of "strategy" are documented:

  1. Scanner strategy presets (STRATEGY_MODES in index.html) — stock-screening
     filters that surface candidates. These produce *candidates*, not trades, so
     they have no standalone P&L; their description + gating rules are shown.

  2. The paper-backtest options strategy — the hypothetical book maintained by
     daily_picks/paper_trade.py (one long ITM/ATM call per daily bullish pick).
     This DOES have P&L, computed here from the ledger:
       - all-time: realized + unrealized aggregates across every paper trade
       - by-day:   realized P&L grouped by the trading day a trade was CLOSED

When the ledger has no closed trades yet, the performance tables say so plainly
rather than inventing numbers. Re-run after the EOD cron has closed trades to
get populated tables.

Usage:  python tools/strategy_report.py [out.pdf]
"""
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, KeepTogether,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
LEDGER_PATH = REPO_ROOT / "daily_picks" / "paper_ledger.json"
OUT_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else (REPO_ROOT / "strategy_report.pdf")

# Brand palette (matches the dashboard's dark-on-cyan theme, but on white for print).
INK = colors.HexColor("#0a1521")
CYAN = colors.HexColor("#0077a3")
CYAN_BG = colors.HexColor("#e6f6fb")
MUTED = colors.HexColor("#5a6b7a")
GREEN = colors.HexColor("#1d8a5e")
RED = colors.HexColor("#c0492a")
RULE = colors.HexColor("#c9d6df")
ROW_ALT = colors.HexColor("#f3f7fa")


# ---------------------------------------------------------------------------
# Static content: the scanner presets + the paper-backtest options strategy.
# Descriptions are plain-English rewrites of the STRATEGY_MODES entries in
# index.html (kept in sync manually; the gating rules are the source of truth).
# ---------------------------------------------------------------------------
SCANNER_PRESETS = [
    {
        "name": "★ HIGH CONVICTION",
        "what": "The rarest, highest-quality setups. A name only appears if it clears every "
                "gate at once — so most scans return just 0–5 matches.",
        "gates": "GO signal · Score ≥ 121 · PROVEN ticker · Analyst revisions rising · "
                 "GEX call-heavy flow · JT 12-1 momentum · Minervini trend template. "
                 "The two highest-edge rules (JT 12-1, Minervini) are MUST-PASS.",
    },
    {
        "name": "▲ BREAKOUT",
        "what": "Chart-pattern breakout buying — stocks pushing into new highs with momentum "
                "and leadership, filtered to weed out fake-outs that only look extended.",
        "gates": "GO signal · Score ≥ 115 · Near 52-week high · RS > SPY · MACD positive · "
                 "Timeframes aligned (2 of 3) · Donchian 20-day breakout · VCP pattern.",
    },
    {
        "name": "▶ MOMENTUM",
        "what": "Confirmed trending stocks with a sector tailwind, gated by the academic "
                "gold-standard 12-minus-1-month momentum signal (the strongest replicated "
                "edge in equity markets).",
        "gates": "GO signal · Score ≥ 111 · MACD positive · Above EMA200 · RS > SPY · "
                 "Strong sector · JT 12-1 momentum (MUST-PASS).",
    },
    {
        "name": "◆ BEST ITM CALLS",
        "what": "Deep in-the-money (delta 0.70–0.90) call ideas on liquid, in-play names where "
                "you're paying real premium — so only setups confirmed by all three top rules "
                "graduate.",
        "gates": "GO signal · Score ≥ 138 · Price ≥ $5 · Avg vol ≥ 1M · In-play today · "
                 "Contract ≤ $8 · JT 12-1 · Minervini · Pocket Pivot.",
    },
    {
        "name": "▲ PRE / POST MARKET",
        "what": "Extended-hours gappers screened with the same gates as High Conviction, then "
                "sorted by absolute gap %. Use during pre/post sessions or on weekends.",
        "gates": "Same gates as High Conviction · Sorted by gap %.",
    },
]

# The single mechanical options strategy that is actually paper-traded.
PAPER_STRATEGY = {
    "name": "Long ITM/ATM Call (single leg)",
    "lines": [
        ("Instrument", "One long call option per pick — a single-leg, defined-risk bullish bet. "
                       "Max loss is the premium paid; upside is uncapped. No spreads, no short legs."),
        ("Universe / entry signal", "Each trading day, the daily-picks filter pulls bullish names from the "
                       "GEX flow snapshot: call flow ≥ 70%, net GEX > 0 (positive-gamma drift), and "
                       "25–50 days to expiry."),
        ("Contract selection", "For each pick, the script buys the single best call: strike between "
                       "0.95× and 1.01× spot (slightly ITM to ATM, ~0.55–0.75 delta), open interest "
                       "≥ 100 for liquidity, ranked by OI then closeness to spot."),
        ("Fill price", "Entered at the contract mid (midpoint of bid/ask) — an optimistic but "
                       "consistent fill assumption. Paper results ignore slippage and commissions."),
        ("Exit rules", "A position is closed at the option's expiry (valued at intrinsic vs. the "
                       "current spot) or after it has been held 15 calendar days, whichever comes first."),
        ("P&amp;L measure", "Return is percent change on the premium: (exit mid − entry mid) / entry mid. "
                       "A trade is a 'win' if that is positive."),
    ],
}


# ---------------------------------------------------------------------------
# Performance computed from the ledger
# ---------------------------------------------------------------------------
def load_trades():
    try:
        led = json.loads(LEDGER_PATH.read_text())
        return led.get("trades", []) if isinstance(led, dict) else []
    except Exception:
        return []


def _avg(vals):
    v = [x for x in vals if isinstance(x, (int, float))]
    return sum(v) / len(v) if v else None


def all_time_stats(trades):
    closed = [t for t in trades if t.get("status") == "closed"]
    opens = [t for t in trades if t.get("status") == "open"]
    cp = [t.get("pnl_pct") for t in closed]
    wins = [x for x in cp if isinstance(x, (int, float)) and x > 0]
    return {
        "n_total": len(trades),
        "n_open": len(opens),
        "n_closed": len(closed),
        "realized_avg": _avg(cp),
        "unreal_avg": _avg([t.get("pnl_pct") for t in opens]),
        "win_rate": (len(wins) / len(cp)) if cp else None,
        "best": max(cp) if cp else None,
        "worst": min(cp) if cp else None,
    }


def by_day_stats(trades):
    """Realized P&L grouped by the day each trade was CLOSED."""
    buckets = defaultdict(list)
    for t in trades:
        if t.get("status") == "closed" and t.get("close_date"):
            buckets[t["close_date"]].append(t.get("pnl_pct"))
    rows = []
    for day in sorted(buckets):
        pnls = [p for p in buckets[day] if isinstance(p, (int, float))]
        if not pnls:
            continue
        wins = [p for p in pnls if p > 0]
        rows.append({
            "day": day,
            "n": len(pnls),
            "avg": sum(pnls) / len(pnls),
            "win_rate": len(wins) / len(pnls),
            "best": max(pnls),
            "worst": min(pnls),
        })
    return rows


# ---------------------------------------------------------------------------
# PDF rendering helpers
# ---------------------------------------------------------------------------
def _fmt_pct(v):
    if not isinstance(v, (int, float)):
        return "—"
    return f"{'+' if v >= 0 else ''}{v:.2f}%"


def _pct_color(v):
    if not isinstance(v, (int, float)):
        return MUTED
    return GREEN if v >= 0 else RED


def build_pdf():
    trades = load_trades()
    at = all_time_stats(trades)
    by_day = by_day_stats(trades)

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], textColor=INK, fontSize=22,
                        spaceAfter=2, leading=26)
    sub = ParagraphStyle("sub", parent=styles["Normal"], textColor=MUTED, fontSize=9.5,
                         spaceAfter=10)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=CYAN, fontSize=14,
                        spaceBefore=14, spaceAfter=6)
    h3 = ParagraphStyle("h3", parent=styles["Heading3"], textColor=INK, fontSize=11.5,
                        spaceBefore=8, spaceAfter=2)
    body = ParagraphStyle("body", parent=styles["Normal"], textColor=INK, fontSize=9.7,
                          leading=13.5, spaceAfter=4)
    small = ParagraphStyle("small", parent=styles["Normal"], textColor=MUTED, fontSize=8.5,
                           leading=11)
    label = ParagraphStyle("label", parent=styles["Normal"], textColor=MUTED, fontSize=8,
                           leading=10)
    cellL = ParagraphStyle("cellL", parent=styles["Normal"], textColor=INK, fontSize=8.6,
                           leading=11)

    flow = []
    today = datetime.now(timezone(timedelta(hours=-5))).strftime("%A, %B %d %Y")

    flow.append(Paragraph("Option Panda — Strategy &amp; Paper-Backtest Report", h1))
    flow.append(Paragraph(f"Generated {today}  ·  long-calls-only swing framework", sub))
    flow.append(HRFlowable(width="100%", thickness=1.2, color=CYAN, spaceAfter=6))

    # ---- Section 1: scanner presets ----------------------------------------
    flow.append(Paragraph("1 · Scanner Strategy Presets", h2))
    flow.append(Paragraph(
        "These are <b>screening filters</b>, not trades. Each preset surfaces a different flavour "
        "of candidate from the daily scan; you still choose the contract and entry. Because they "
        "produce candidates rather than positions, they carry no standalone trade P&amp;L — the "
        "performance section below covers the one strategy that is actually paper-traded.", body))

    preset_rows = [[Paragraph("PRESET", label), Paragraph("WHAT IT IS", label),
                    Paragraph("GATING RULES (all must pass)", label)]]
    for p in SCANNER_PRESETS:
        preset_rows.append([
            Paragraph(f"<b>{p['name']}</b>", cellL),
            Paragraph(p["what"], cellL),
            Paragraph(p["gates"], small),
        ])
    t = Table(preset_rows, colWidths=[1.35 * inch, 2.55 * inch, 3.0 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, RULE),
    ]))
    flow.append(t)

    # ---- Section 2: paper-backtest options strategy ------------------------
    flow.append(Paragraph("2 · The Paper-Backtested Options Strategy", h2))
    flow.append(Paragraph(
        f"<b>{PAPER_STRATEGY['name']}.</b>  This is the single mechanical strategy tracked by the "
        "paper book. Every bullish pick is turned into one hypothetical long call so the approach "
        "can be scored objectively over time.", body))
    spec_rows = []
    for k, v in PAPER_STRATEGY["lines"]:
        spec_rows.append([Paragraph(f"<b>{k}</b>", cellL), Paragraph(v, cellL)])
    t2 = Table(spec_rows, colWidths=[1.5 * inch, 5.4 * inch])
    t2.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("BACKGROUND", (0, 0), (0, -1), CYAN_BG),
        ("ROWBACKGROUNDS", (1, 0), (1, -1), [colors.white, ROW_ALT]),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, RULE),
    ]))
    flow.append(t2)

    # ---- Section 3: performance --------------------------------------------
    flow.append(Paragraph("3 · Paper-Book Performance", h2))

    if at["n_total"] == 0:
        box = Table([[Paragraph(
            "<b>No paper trades recorded yet.</b><br/>The paper book opens its first positions on the "
            "next scheduled run of the end-of-day cron (or a manual <i>Actions → Paper Trade "
            "Performance → Run workflow</i>). All-time and by-day tables populate automatically "
            "from that point — re-run this report once trades have closed.", body)]],
            colWidths=[6.9 * inch])
        box.setStyle(TableStyle([
            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#d9a441")),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fdf6e3")),
            ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ]))
        flow.append(box)
    else:
        # All-time scorecard
        flow.append(Paragraph("All-time", h3))
        wr = at["win_rate"]
        cards = [
            ("OPEN", str(at["n_open"]), INK),
            ("CLOSED", str(at["n_closed"]), INK),
            ("AVG REALIZED", _fmt_pct(at["realized_avg"]), _pct_color(at["realized_avg"])),
            ("AVG UNREALIZED", _fmt_pct(at["unreal_avg"]), _pct_color(at["unreal_avg"])),
            ("WIN RATE", f"{wr*100:.0f}%" if wr is not None else "—", INK),
            ("BEST / WORST", f"{_fmt_pct(at['best'])} / {_fmt_pct(at['worst'])}", INK),
        ]
        card_cells, card_styles = [[], []], []
        for i, (lab, val, col) in enumerate(cards):
            card_cells[0].append(Paragraph(f"<b>{val}</b>", ParagraphStyle(
                "v", parent=body, fontSize=13, textColor=col, alignment=1)))
            card_cells[1].append(Paragraph(lab, ParagraphStyle(
                "l", parent=label, alignment=1)))
        ct = Table(card_cells, colWidths=[6.9 / 6 * inch] * 6)
        ct.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), CYAN_BG),
            ("TOPPADDING", (0, 0), (-1, 0), 9), ("BOTTOMPADDING", (0, 1), (-1, 1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.white),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        flow.append(ct)

        # By-day table
        flow.append(Paragraph("By day (realized, grouped by close date)", h3))
        hdr = [Paragraph(x, label) for x in ["DATE", "TRADES", "AVG P/L", "WIN RATE", "BEST", "WORST"]]
        day_rows = [hdr]
        for r in by_day:
            day_rows.append([
                Paragraph(r["day"], cellL),
                Paragraph(str(r["n"]), cellL),
                Paragraph(f"<font color='#{_pct_color(r['avg']).hexval()[2:]}'>{_fmt_pct(r['avg'])}</font>", cellL),
                Paragraph(f"{r['win_rate']*100:.0f}%", cellL),
                Paragraph(_fmt_pct(r["best"]), cellL),
                Paragraph(_fmt_pct(r["worst"]), cellL),
            ])
        dt = Table(day_rows, colWidths=[1.3*inch, 0.9*inch, 1.1*inch, 1.1*inch, 1.2*inch, 1.3*inch])
        dt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), INK),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT]),
            ("LINEBELOW", (0, 0), (-1, -1), 0.5, RULE),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ]))
        flow.append(dt)

    # ---- Footer ------------------------------------------------------------
    flow.append(Spacer(1, 14))
    flow.append(HRFlowable(width="100%", thickness=0.6, color=RULE, spaceAfter=4))
    flow.append(Paragraph(
        "Hypothetical results. Paper fills assume entry at the mid and ignore slippage, partial "
        "fills, and commissions; they do not represent actual trading and are not financial advice. "
        "Scanner presets are screening tools, not signals to trade. Source: Option Panda "
        "daily_picks/paper_ledger.json + index.html STRATEGY_MODES.", small))

    doc = SimpleDocTemplate(
        str(OUT_PATH), pagesize=letter,
        leftMargin=0.55 * inch, rightMargin=0.55 * inch,
        topMargin=0.5 * inch, bottomMargin=0.5 * inch,
        title="Option Panda Strategy & Paper-Backtest Report",
    )
    doc.build(flow)
    sys.stderr.write(f"[strategy-report] wrote {OUT_PATH} ({at['n_closed']} closed, {at['n_open']} open)\n")


if __name__ == "__main__":
    build_pdf()
