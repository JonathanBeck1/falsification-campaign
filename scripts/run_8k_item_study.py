#!/usr/bin/env python
"""Run the pre-registered SEC 8-K item-type event study."""

from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
import structlog

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trader.catalysts.event_driven import (  # noqa: E402
    classify_8k_items,
    compute_event_cars,
)
from trader.catalysts.prices import fetch_daily  # noqa: E402

structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(20))
log = structlog.get_logger()

# Pre-registered parameters.
TICKERS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "GOOG", "TSLA", "BRK-B", "JPM",
    "V", "MA", "UNH", "LLY", "JNJ", "XOM", "WMT", "HD", "PG", "COST",
    "AVGO", "ORCL", "ADBE", "CRM", "NFLX", "AMD", "INTC", "QCOM", "CSCO", "PEP",
]
SINCE = date(2020, 1, 1)
UNTIL = date(2024, 12, 31)
OOS_SPLIT_YEAR = 2022
ITEM_CODES = ("1.01", "2.02", "5.02", "7.01")
WINDOWS = {"car_0_p5": (0, 5), "car_0_p21": (0, 21)}

OUT_DIR = ROOT / "output" / "catalysts"
REPORT_PATH = ROOT / "research" / "event_driven_8k_report.md"
JSON_PATH = OUT_DIR / "event_driven_8k.json"


@dataclass(frozen=True)
class FilingEvent:
    ticker: str
    filing_date: date
    items: frozenset[str]


@dataclass(frozen=True)
class ItemObservation:
    filing_date: date
    car_0_p5: float
    car_0_p21: float


@dataclass(frozen=True)
class ItemStats:
    code: str
    n: int
    means: dict[str, float]
    medians: dict[str, float]
    t_stats: dict[str, float]


def _t_stat(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    series = pd.Series(values)
    std = float(series.std(ddof=1))
    if std == 0:
        return 0.0
    return float(series.mean() / (std / math.sqrt(len(values))))


def _aggregate(code: str, observations: list[ItemObservation]) -> ItemStats:
    values = {
        name: [float(getattr(observation, name)) for observation in observations]
        for name in WINDOWS
    }
    return ItemStats(
        code=code,
        n=len(observations),
        means={
            name: float(pd.Series(metric_values).mean()) if metric_values else float("nan")
            for name, metric_values in values.items()
        },
        medians={
            name: float(pd.Series(metric_values).median()) if metric_values else float("nan")
            for name, metric_values in values.items()
        },
        t_stats={
            name: _t_stat(metric_values) for name, metric_values in values.items()
        },
    )


def _welch_t(left: list[float], right: list[float]) -> float:
    if len(left) < 2 or len(right) < 2:
        return 0.0
    left_series = pd.Series(left)
    right_series = pd.Series(right)
    denominator = math.sqrt(
        float(left_series.var(ddof=1)) / len(left)
        + float(right_series.var(ddof=1)) / len(right)
    )
    if denominator == 0 or denominator != denominator:
        return 0.0
    return float((left_series.mean() - right_series.mean()) / denominator)


def _item_values(
    buckets: dict[str, list[ItemObservation]],
    code: str,
    *,
    early: bool | None = None,
) -> list[float]:
    observations = buckets[code]
    if early is True:
        observations = [
            observation
            for observation in observations
            if observation.filing_date.year <= OOS_SPLIT_YEAR
        ]
    elif early is False:
        observations = [
            observation
            for observation in observations
            if observation.filing_date.year > OOS_SPLIT_YEAR
        ]
    return [observation.car_0_p21 for observation in observations]


def _mean_difference(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return float("nan")
    return float(pd.Series(left).mean() - pd.Series(right).mean())


def _fmt_item_table(stats: dict[str, ItemStats]) -> str:
    rows = [
        "| item | n | mean [0,+5] % | median [0,+5] % | t | mean [0,+21] % | median [0,+21] % | t |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for code in ITEM_CODES:
        item = stats[code]
        rows.append(
            f"| {code} | {item.n} | {item.means['car_0_p5'] * 100:+.2f} | "
            f"{item.medians['car_0_p5'] * 100:+.2f} | {item.t_stats['car_0_p5']:+.2f} | "
            f"{item.means['car_0_p21'] * 100:+.2f} | "
            f"{item.medians['car_0_p21'] * 100:+.2f} | {item.t_stats['car_0_p21']:+.2f} |"
        )
    return "\n".join(rows)


def main() -> int:
    from edgar import Company, set_identity

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    set_identity(os.getenv("TRADER_SEC_USER_AGENT", "trader-research research@example.com"))

    spy = fetch_daily("SPY", SINCE - timedelta(days=100), UNTIL + timedelta(days=100))
    if spy is None:
        print("ERROR: could not fetch SPY", file=sys.stderr)
        return 2
    spy_close, _ = spy

    buckets: dict[str, list[ItemObservation]] = {code: [] for code in ITEM_CODES}
    warnings: list[str] = []
    filings_seen = 0
    classified_filings = 0
    usable_filings = 0

    for index, ticker in enumerate(TICKERS, start=1):
        if index % 5 == 0:
            log.info(
                "event_driven_8k_progress",
                done=index,
                total=len(TICKERS),
                filings=filings_seen,
                usable=usable_filings,
            )
        if ticker == "BRK-B":
            warnings.append("BRK-B: skipped per pre-registration")
            continue

        filing_events: list[FilingEvent] = []
        try:
            company = Company(ticker)
            filings = company.get_filings(
                form="8-K",
                date=f"{SINCE.isoformat()}:{UNTIL.isoformat()}",
            )
            for filing in filings:
                filings_seen += 1
                try:
                    text = filing.text()
                    items = classify_8k_items(text)
                    filing_date = pd.Timestamp(filing.filing_date).date()
                except Exception as exc:
                    log.warning(
                        "event_driven_8k_text_failed",
                        ticker=ticker,
                        error=str(exc),
                    )
                    continue
                relevant = frozenset(items.intersection(ITEM_CODES))
                if not relevant:
                    continue
                classified_filings += 1
                filing_events.append(
                    FilingEvent(
                        ticker=ticker,
                        filing_date=filing_date,
                        items=relevant,
                    )
                )
        except Exception as exc:
            warnings.append(f"{ticker}: EDGAR filings unavailable ({exc})")
            log.warning("event_driven_8k_filings_failed", ticker=ticker, error=str(exc))
            continue

        if not filing_events:
            continue
        prices = fetch_daily(
            ticker,
            SINCE - timedelta(days=100),
            UNTIL + timedelta(days=100),
        )
        if prices is None:
            warnings.append(f"{ticker}: price history unavailable")
            continue
        close, _ = prices

        for filing_event in filing_events:
            cars = compute_event_cars(
                close,
                spy_close,
                filing_event.filing_date,
                WINDOWS,
            )
            if not cars:
                continue
            usable_filings += 1
            observation = ItemObservation(
                filing_date=filing_event.filing_date,
                car_0_p5=float(cars["car_0_p5"]),
                car_0_p21=float(cars["car_0_p21"]),
            )
            for code in filing_event.items:
                buckets[code].append(observation)

    stats = {code: _aggregate(code, buckets[code]) for code in ITEM_CODES}
    item_202 = _item_values(buckets, "2.02")
    item_701 = _item_values(buckets, "7.01")
    primary_diff = _mean_difference(item_202, item_701)
    primary_t = _welch_t(item_202, item_701)
    early_diff = _mean_difference(
        _item_values(buckets, "2.02", early=True),
        _item_values(buckets, "7.01", early=True),
    )
    late_diff = _mean_difference(
        _item_values(buckets, "2.02", early=False),
        _item_values(buckets, "7.01", early=False),
    )

    separation_pass = abs(primary_t) >= 2.0
    item_101_pass = (
        stats["1.01"].means["car_0_p21"] > 0
        and stats["1.01"].t_stats["car_0_p21"] >= 2.0
    )
    item_502_pass = abs(stats["5.02"].t_stats["car_0_p21"]) < 2.0
    gate_passed = separation_pass and item_101_pass and item_502_pass
    reasons = [
        f"{'PASS' if separation_pass else 'FAIL'}: Item 2.02 minus 7.01 "
        f"car_0_p21 diff={primary_diff:+.4f}, Welch t={primary_t:+.2f} (need |t| >= 2.0)",
        f"{'PASS' if item_101_pass else 'FAIL'}: Item 1.01 mean="
        f"{stats['1.01'].means['car_0_p21']:+.4f}, t="
        f"{stats['1.01'].t_stats['car_0_p21']:+.2f} (need mean > 0 and t >= 2.0)",
        f"{'PASS' if item_502_pass else 'FAIL'}: Item 5.02 t="
        f"{stats['5.02'].t_stats['car_0_p21']:+.2f} (need |t| < 2.0)",
    ]

    run_at = datetime.now(UTC).isoformat()
    warning_lines = [f"- {warning}" for warning in warnings] or ["- None"]
    lines = [
        "# SEC 8-K Item-Type Event Study Result",
        "",
        "Pre-registration: `research/event_driven_8k_preregistration.md`.",
        "",
        "## Run metadata",
        f"- Run at: {run_at}",
        f"- Filing window: {SINCE} .. {UNTIL}",
        f"- Fixed universe: {len(TICKERS)} symbols (BRK-B pre-registered skip)",
        "- Benchmark: SPY; abnormal return = stock return minus SPY return (beta=1)",
        f"- OOS split: filing year <= {OOS_SPLIT_YEAR} vs > {OOS_SPLIT_YEAR}",
        "",
        "## Sample accounting",
        f"- Filings inspected: {filings_seen}",
        f"- Filings with a target item: {classified_filings}",
        f"- Filings with usable CARs: {usable_filings}",
        "",
        "## Item cohorts",
        _fmt_item_table(stats),
        "",
        "## Primary comparison",
        f"- Item 2.02 minus Item 7.01 mean car_0_p21: {primary_diff:+.4f}",
        f"- Welch t-statistic: {primary_t:+.2f}",
        f"- Early-half difference: {early_diff:+.4f}",
        f"- Late-half difference: {late_diff:+.4f}",
        "",
        "## Pre-registered gate verdict",
        f"### {'PASS' if gate_passed else 'FAIL'}",
        *[f"- {reason}" for reason in reasons],
        "",
        "## Coverage warnings",
        *warning_lines,
        "",
    ]

    try:
        REPORT_PATH.write_text("\n".join(lines))
        JSON_PATH.write_text(
            json.dumps(
                {
                    "run_at": run_at,
                    "n_filings": usable_filings,
                    "items": {
                        code: {
                            "n": item.n,
                            "mean_car_0_p21": item.means["car_0_p21"],
                            "t_stat": item.t_stats["car_0_p21"],
                        }
                        for code, item in stats.items()
                    },
                    "diff_t_stats": {"item_2.02_vs_7.01": primary_t},
                    "gate_passed": gate_passed,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
    except OSError as exc:
        print(f"ERROR: could not write study outputs: {exc}", file=sys.stderr)
        return 3

    print("\n".join(lines[-min(12, len(lines)) :]))
    print(f"Report written: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
