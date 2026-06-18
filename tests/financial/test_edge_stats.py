from __future__ import annotations

from trader.research.edge_stats import (
    EdgeBucket,
    EdgeDecisionConfig,
    classify_edge_bucket,
    summarize_returns,
)


def test_summarize_returns_computes_net_stats():
    summary = summarize_returns(
        bucket="macro_surprise|negative|breaking",
        horizon="15m",
        returns_bps=[20.0, 30.0, -10.0, 40.0, 25.0],
        cost_bps=2.0,
    )

    assert summary.bucket == "macro_surprise|negative|breaking"
    assert summary.horizon == "15m"
    assert summary.n == 5
    assert round(summary.mean_bps, 2) == 21.0
    assert round(summary.net_mean_bps, 2) == 19.0
    assert round(summary.hit_rate, 2) == 0.8
    assert summary.t_stat > 1.0


def test_classify_edge_bucket_rejects_small_sample():
    bucket = EdgeBucket(
        bucket="fed_commentary|neutral|normal",
        horizon="15m",
        n=8,
        mean_bps=10.0,
        net_mean_bps=8.0,
        median_bps=6.0,
        hit_rate=0.7,
        stdev_bps=15.0,
        t_stat=1.5,
        cost_bps=2.0,
    )

    verdict = classify_edge_bucket(bucket, EdgeDecisionConfig(min_n=30))

    assert verdict.verdict == "insufficient_sample"
    assert "n=8 < min_n=30" in verdict.reason


def test_classify_edge_bucket_accepts_positive_net_with_tstat():
    bucket = EdgeBucket(
        bucket="guidance_raise|positive|high",
        horizon="1h",
        n=40,
        mean_bps=18.0,
        net_mean_bps=16.0,
        median_bps=11.0,
        hit_rate=0.65,
        stdev_bps=35.0,
        t_stat=2.89,
        cost_bps=2.0,
    )

    verdict = classify_edge_bucket(
        bucket,
        EdgeDecisionConfig(min_n=30, min_t_stat=2.0, min_net_mean_bps=5.0),
    )

    assert verdict.verdict == "candidate_edge"
    assert "t_stat=2.89" in verdict.reason


def test_classify_edge_bucket_rejects_negative_net_mean():
    bucket = EdgeBucket(
        bucket="other|neutral|normal",
        horizon="5m",
        n=50,
        mean_bps=1.0,
        net_mean_bps=-1.0,
        median_bps=0.0,
        hit_rate=0.51,
        stdev_bps=20.0,
        t_stat=0.35,
        cost_bps=2.0,
    )

    verdict = classify_edge_bucket(bucket, EdgeDecisionConfig())

    assert verdict.verdict == "no_edge"
    assert "net_mean_bps=-1.00" in verdict.reason
