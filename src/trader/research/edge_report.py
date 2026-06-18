"""Research-only edge validation reports from event outcome backtests."""

from __future__ import annotations

import math

from trader.research.edge_stats import EdgeBucket, EdgeDecisionConfig, EdgeVerdict, classify_edge_bucket
from trader.research.outcome_review import OutcomeReportData, OutcomeStatRow, parse_outcome_report


def build_edge_rows_from_outcome_report(
    markdown: str,
    *,
    min_n: int,
    cost_bps: float,
    min_t_stat: float = 2.0,
    min_net_mean_bps: float = 5.0,
    min_hit_rate: float = 0.55,
) -> list[tuple[EdgeBucket, EdgeVerdict]]:
    if min_n < 1:
        raise ValueError("min_n must be at least 1")
    if cost_bps < 0:
        raise ValueError("cost_bps must be non-negative")

    data = parse_outcome_report(markdown)
    return build_edge_rows(
        data,
        EdgeDecisionConfig(
            min_n=min_n,
            min_t_stat=min_t_stat,
            min_net_mean_bps=min_net_mean_bps,
            min_hit_rate=min_hit_rate,
        ),
        cost_bps=cost_bps,
    )


def build_edge_rows(
    data: OutcomeReportData,
    config: EdgeDecisionConfig,
    *,
    cost_bps: float,
) -> list[tuple[EdgeBucket, EdgeVerdict]]:
    rows: list[tuple[EdgeBucket, EdgeVerdict]] = []
    for stat in data.grouped_stats:
        bucket = _bucket_from_outcome_stat(stat, cost_bps=cost_bps)
        rows.append((bucket, classify_edge_bucket(bucket, config)))
    return sorted(rows, key=_edge_row_sort_key)


def format_edge_report(
    rows: list[tuple[EdgeBucket, EdgeVerdict]],
    *,
    source_path: str,
    min_n: int,
    cost_bps: float,
) -> str:
    lines = [
        "# Edge Validation Report",
        "",
        "This is research-only. It is not a live trading signal, investment advice, or proof of future performance.",
        "",
        "## Run Metadata",
        "",
        f"- source_path: `{source_path}`",
        f"- min_n: {min_n}",
        f"- cost_bps: {cost_bps:.2f}",
        "",
        "## Bucket Verdicts",
        "",
    ]

    if not rows:
        lines.append("No bucket verdicts parsed from the outcome report.")
        lines.append("")
        return "\n".join(lines)

    lines.extend(
        [
            "| verdict | bucket | horizon | n | mean_bps | net_mean_bps | t_stat | hit_rate | reason |",
            "|---|---|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for bucket, verdict in rows:
        lines.append(
            "| "
            f"{_format_table_cell(verdict.verdict)} | "
            f"{_format_table_cell(bucket.bucket)} | "
            f"{_format_table_cell(bucket.horizon)} | "
            f"{bucket.n} | "
            f"{bucket.mean_bps:.2f} | "
            f"{bucket.net_mean_bps:.2f} | "
            f"{bucket.t_stat:.2f} | "
            f"{bucket.hit_rate:.2f} | "
            f"{_format_table_cell(verdict.reason)} |"
        )
    lines.append("")
    lines.extend(
        [
            "## Interpretation Rules",
            "",
            "- `candidate_edge` means this bucket cleared the configured first-pass statistical gate only.",
            "- Every candidate still needs out-of-sample validation, latency/slippage checks, and manual review.",
            "- `insufficient_sample`, `weak_evidence`, and `no_edge` buckets are not deployable signals.",
            "",
        ]
    )
    return "\n".join(lines)


def _bucket_from_outcome_stat(stat: OutcomeStatRow, *, cost_bps: float) -> EdgeBucket:
    mean_bps = stat.mean_return_pct * 100
    median_bps = stat.median_return_pct * 100
    stdev_bps = stat.stdev_return_pct * 100
    t_stat = (mean_bps / (stdev_bps / math.sqrt(stat.n))) if stdev_bps > 0 and stat.n > 1 else 0.0
    return EdgeBucket(
        bucket=stat.group,
        horizon=stat.horizon,
        n=stat.n,
        mean_bps=mean_bps,
        net_mean_bps=mean_bps - cost_bps,
        median_bps=median_bps,
        hit_rate=stat.hit_rate,
        stdev_bps=stdev_bps,
        t_stat=t_stat,
        cost_bps=cost_bps,
    )


def _edge_row_sort_key(row: tuple[EdgeBucket, EdgeVerdict]) -> tuple[int, int, float, float, str, str]:
    bucket, verdict = row
    verdict_rank = {
        "candidate_edge": 0,
        "weak_evidence": 1,
        "no_edge": 2,
        "insufficient_sample": 3,
    }.get(verdict.verdict, 4)
    return (verdict_rank, -bucket.n, -bucket.net_mean_bps, -abs(bucket.t_stat), bucket.bucket, bucket.horizon)


def _format_table_cell(value: object) -> str:
    return " ".join(str(value).split()).replace("|", "\\|")
