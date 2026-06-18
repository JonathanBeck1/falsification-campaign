from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import mean, median, stdev


@dataclass(frozen=True)
class EdgeBucket:
    bucket: str
    horizon: str
    n: int
    mean_bps: float
    net_mean_bps: float
    median_bps: float
    hit_rate: float
    stdev_bps: float
    t_stat: float
    cost_bps: float


@dataclass(frozen=True)
class EdgeDecisionConfig:
    min_n: int = 30
    min_t_stat: float = 2.0
    min_net_mean_bps: float = 5.0
    min_hit_rate: float = 0.55


@dataclass(frozen=True)
class EdgeVerdict:
    verdict: str
    reason: str


def summarize_returns(
    *,
    bucket: str,
    horizon: str,
    returns_bps: list[float],
    cost_bps: float,
) -> EdgeBucket:
    if not returns_bps:
        return EdgeBucket(
            bucket=bucket,
            horizon=horizon,
            n=0,
            mean_bps=0.0,
            net_mean_bps=-cost_bps,
            median_bps=0.0,
            hit_rate=0.0,
            stdev_bps=0.0,
            t_stat=0.0,
            cost_bps=cost_bps,
        )

    n = len(returns_bps)
    avg = mean(returns_bps)
    med = median(returns_bps)
    hit = sum(1 for value in returns_bps if value > 0) / n
    sd = stdev(returns_bps) if n > 1 else 0.0
    t_stat = (avg / (sd / math.sqrt(n))) if sd > 0 and n > 1 else 0.0
    return EdgeBucket(
        bucket=bucket,
        horizon=horizon,
        n=n,
        mean_bps=avg,
        net_mean_bps=avg - cost_bps,
        median_bps=med,
        hit_rate=hit,
        stdev_bps=sd,
        t_stat=t_stat,
        cost_bps=cost_bps,
    )


def classify_edge_bucket(bucket: EdgeBucket, config: EdgeDecisionConfig) -> EdgeVerdict:
    if bucket.n < config.min_n:
        return EdgeVerdict(
            verdict="insufficient_sample",
            reason=f"n={bucket.n} < min_n={config.min_n}",
        )
    if bucket.net_mean_bps < config.min_net_mean_bps:
        return EdgeVerdict(
            verdict="no_edge",
            reason=(
                f"net_mean_bps={bucket.net_mean_bps:.2f} "
                f"< min_net_mean_bps={config.min_net_mean_bps:.2f}"
            ),
        )
    if bucket.t_stat < config.min_t_stat:
        return EdgeVerdict(
            verdict="weak_evidence",
            reason=f"t_stat={bucket.t_stat:.2f} < min_t_stat={config.min_t_stat:.2f}",
        )
    if bucket.hit_rate < config.min_hit_rate:
        return EdgeVerdict(
            verdict="weak_evidence",
            reason=f"hit_rate={bucket.hit_rate:.2f} < min_hit_rate={config.min_hit_rate:.2f}",
        )
    return EdgeVerdict(
        verdict="candidate_edge",
        reason=(
            f"n={bucket.n}, net_mean_bps={bucket.net_mean_bps:.2f}, "
            f"t_stat={bucket.t_stat:.2f}, hit_rate={bucket.hit_rate:.2f}"
        ),
    )
