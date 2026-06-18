#!/usr/bin/env python
"""Run the REAL CEF discount-capture survival backtest and write the report.

Loads the 82 Saba campaigns, joins each with its resolution OUTCOME (parsed from
``research/cef_resolution_report.md`` — ticker, sponsor, class, outcome, res_date,
days), builds the yfinance+Tiingo price provider, runs the survival backtest, and
writes ``research/cef_survival_backtest_report.md``.

Graceful degradation: if ``TIINGO_API_KEY`` is unset the script prints the
get-a-key instructions and STILL runs on whatever yfinance serves — but yfinance
purges delisted symbols, which are exactly the resolved winners, so the run will
be missing most of the upside. The report says so explicitly and reports how many
resolved names could not be priced.

Usage:
    TIINGO_API_KEY=... .venv/bin/python scripts/run_cef_survival.py
"""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path

import structlog

from trader.catalysts.cef_resolution import load_campaigns
from trader.catalysts.cef_survival_backtest import (
    Campaign,
    evaluate_gate,
    make_provider,
    run_backtest,
)

log = structlog.get_logger()

REPO = Path(__file__).resolve().parents[1]
CAMPAIGNS_CSV = REPO / "output" / "catalysts" / "saba_cef_campaigns.csv"
RESOLUTION_REPORT = REPO / "research" / "cef_resolution_report.md"
OUT_REPORT = REPO / "research" / "cef_survival_backtest_report.md"

RESOLVED_OUTCOMES = frozenset({"deregistered", "delisted", "merger", "tender"})


def parse_resolution_labels(path: Path) -> dict[str, dict]:
    """Parse the per-campaign labels table (§3) keyed by ticker.

    Returns ``{ticker: {sponsor, is_municipal, outcome, resolved, res_date}}``.
    Rows look like:
      ``| NDP | ... | 2022-01-10 | Tortoise | eq/alt | **delisted** | 25-NSE | 2024-12-23 | 1078 |``
    """

    labels: dict[str, dict] = {}
    text = path.read_text()
    row_re = re.compile(r"^\|(.+)\|\s*$")
    for line in text.splitlines():
        m = row_re.match(line.strip())
        if not m:
            continue
        cells = [c.strip() for c in m.group(1).split("|")]
        if len(cells) < 9:
            continue
        ticker = cells[0]
        # Skip header/separator rows.
        if ticker in ("Ticker", "") or set(ticker) <= set("-: "):
            continue
        sponsor = cells[3]
        cls = cells[4]
        outcome = cells[5].replace("*", "").strip().lower()
        res_date_raw = cells[7].strip()
        if outcome not in (RESOLVED_OUTCOMES | {"ongoing"}):
            continue
        res_date = None
        if res_date_raw and res_date_raw != "—":
            try:
                res_date = date.fromisoformat(res_date_raw)
            except ValueError:
                res_date = None
        labels[ticker] = {
            "sponsor": sponsor,
            "is_municipal": cls.lower().startswith("muni"),
            "outcome": outcome,
            "resolved": outcome in RESOLVED_OUTCOMES,
            "res_date": res_date,
        }
    return labels


def build_campaigns() -> list[Campaign]:
    """Join the campaign CSV with parsed resolution labels into Campaign rows."""

    rows = load_campaigns(CAMPAIGNS_CSV)
    labels = parse_resolution_labels(RESOLUTION_REPORT)
    campaigns: list[Campaign] = []
    for ticker, _cik, name, filing_date in rows:
        lbl = labels.get(ticker)
        if lbl is None:
            # Unlabeled campaign — treat as ongoing, name-derive muni/sponsor.
            from trader.catalysts.cef_resolution import classify_sponsor, is_municipal_fund

            campaigns.append(
                Campaign(
                    ticker=ticker,
                    name=name,
                    filing_date=filing_date,
                    sponsor=classify_sponsor(name),
                    is_municipal=is_municipal_fund(name),
                    resolved=False,
                    resolution_date=None,
                )
            )
            continue
        campaigns.append(
            Campaign(
                ticker=ticker,
                name=name,
                filing_date=filing_date,
                sponsor=lbl["sponsor"],
                is_municipal=lbl["is_municipal"],
                resolved=lbl["resolved"],
                resolution_date=lbl["res_date"] if lbl["resolved"] else None,
            )
        )
    return campaigns


def _fmt(x: float) -> str:
    return "n/a" if x != x else f"{x:+.4f}"


def _pct(x: float) -> str:
    return "n/a" if x != x else f"{x * 100:.1f}%"


def write_report(result, gate, *, have_key: bool) -> None:
    b = result.untilted
    t = result.tilted
    n_resolved_total = sum(1 for c in result.per_campaign if c.resolved)
    n_resolved_unpriced = sum(1 for c in result.per_campaign if c.resolved and not c.priced)

    key_note = (
        "Tiingo key **present** — delisted (resolved) funds were fetched from Tiingo."
        if have_key
        else "Tiingo key **ABSENT** — ran on yfinance only, which PURGES delisted symbols. "
        "The resolved winners are therefore mostly **missing**, biasing realized "
        "excess DOWNWARD. Treat these numbers as a lower-coverage floor, not the real result."
    )

    lines = [
        "# CEF Discount-Capture — REAL Survival Backtest",
        "",
        "Replaces the bounded estimate in `research/cef_survival_estimate.md` with an",
        "actual realized backtest: buy the fund the trading day after Saba's SC 13D,",
        "hold to the **resolution date** (resolved funds) or a ~2yr cap (ongoing funds),",
        "measure realized return minus the broad-CEF benchmark (PCEF) over the matched",
        "window = discount-capture excess. Pre-registered in",
        "`research/cef_survival_backtest_preregistration.md`.",
        "",
        f"**Data status.** {key_note}",
        "",
        "## Coverage",
        "",
        f"- Campaigns: {result.n_campaigns}",
        f"- Priced (entered & exited): {result.n_priced}",
        f"- Resolved campaigns total: {n_resolved_total}; resolved-but-UNPRICED: {n_resolved_unpriced}",
        f"- Resolved AND priced (the upside actually measured): {result.n_resolved_priced}",
        "",
        "## Realized excess (target minus PCEF over the matched hold)",
        "",
        "| basket | N | mean excess | median excess | mean excess ann. | median hold (yr) | % positive | t-stat |",
        "|---|---|---|---|---|---|---|---|",
        f"| untilted | {b.n} | {_fmt(b.mean_excess)} | {_fmt(b.median_excess)} | "
        f"{_fmt(b.mean_excess_annualized)} | {b.median_holding_years:.2f} | "
        f"{_pct(b.pct_positive)} | {b.t_stat:+.2f} |",
        f"| tilted (muni + fast-sponsor) | {t.n} | {_fmt(t.mean_excess)} | {_fmt(t.median_excess)} | "
        f"{_fmt(t.mean_excess_annualized)} | {t.median_holding_years:.2f} | "
        f"{_pct(t.pct_positive)} | {t.t_stat:+.2f} |",
        "",
        "## Pre-registered gate (tilt edge)",
        "",
        f"**{'PASS' if gate.passed else 'FAIL'}**",
        "",
        *[f"- {r}" for r in gate.reasons],
        "",
        "## Per-campaign realized returns",
        "",
        "| ticker | entry | exit | hold (d) | target | bench | excess | resolved | note |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for c in sorted(result.per_campaign, key=lambda r: (not r.priced, -(r.excess_return if r.priced else 0))):
        lines.append(
            f"| {c.ticker} | {c.entry_date} | {c.exit_date} | {c.holding_days} | "
            f"{_fmt(c.target_return)} | {_fmt(c.bench_return)} | {_fmt(c.excess_return)} | "
            f"{'yes' if c.resolved else 'no'} | {c.note} |"
        )

    lines += [
        "",
        "## Honest caveats",
        "",
        "- **NAV-free, so this is excess OVER the CEF market, not absolute return.** PCEF",
        "  nets out CEF beta and broad discount moves; a held basket also earns the asset",
        "  class return on top.",
        "- **Delisting-price coverage is the whole ballgame.** Without a Tiingo key the",
        "  resolved winners are missing and the result is biased low. WITH a key, Tiingo's",
        "  last marks may predate the actual liquidation/merger cash-out, so realized",
        "  upside is a conservative read of the terminal NAV payoff (we cannot see the",
        "  final liquidation value, only the last traded price).",
        "- **Ongoing funds are right-censored.** Their hold is capped at the max-hold; many",
        "  2024 'ongoing' names are still cooking and may resolve later, so the untilted",
        "  basket understates the eventual resolution rate.",
        "- **Thin per-sponsor cells.** The tilt leans on n=3-5 sponsor cohorts; treat the",
        "  tilt vs untilted gap as directional, not a tight estimate.",
        "- **Frictions not deducted here.** CEFs trade with wide spreads (~1% round-trip);",
        "  subtract that from any mean before sizing. A multi-quarter convex hold, never",
        "  life-changing.",
        "",
        "*Generated by `scripts/run_cef_survival.py`. Pure backtest logic is unit-tested in",
        "`tests/financial/test_cef_survival_backtest.py`; the Tiingo client in",
        "`tests/financial/test_tiingo.py`.*",
    ]
    OUT_REPORT.write_text("\n".join(lines) + "\n")


def main() -> None:
    have_key = bool(os.environ.get("TIINGO_API_KEY", "").strip())
    if not have_key:
        print(
            "\n[!] TIINGO_API_KEY is not set.\n"
            "    Resolved/delisted CEFs are PURGED from yfinance, so the resolution\n"
            "    upside will be largely missing and realized excess will be biased low.\n"
            "    Get a FREE key at https://www.tiingo.com and run:\n"
            "        export TIINGO_API_KEY=...\n"
            "        .venv/bin/python scripts/run_cef_survival.py\n"
            "    Running now on yfinance-only coverage (degraded)...\n"
        )

    campaigns = build_campaigns()
    log.info("survival_loaded_campaigns", n=len(campaigns))
    provider = make_provider()
    result = run_backtest(campaigns, provider, today=date.today())
    gate = evaluate_gate(result)

    write_report(result, gate, have_key=have_key)

    print(f"Campaigns: {result.n_campaigns}  priced: {result.n_priced}  "
          f"resolved&priced: {result.n_resolved_priced}")
    print(f"Untilted mean excess: {_fmt(result.untilted.mean_excess)} "
          f"(t={result.untilted.t_stat:+.2f}, N={result.untilted.n})")
    print(f"Tilted   mean excess: {_fmt(result.tilted.mean_excess)} "
          f"(t={result.tilted.t_stat:+.2f}, N={result.tilted.n})")
    print(f"Gate: {'PASS' if gate.passed else 'FAIL'}")
    for r in gate.reasons:
        print(f"  - {r}")
    print(f"\nReport written to {OUT_REPORT}")
    if not have_key:
        print("\n[!] Reminder: no Tiingo key => resolved winners mostly missing. "
              "Numbers are a lower-coverage floor.")


if __name__ == "__main__":
    main()
