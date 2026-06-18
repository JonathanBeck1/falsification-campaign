"""Pin the THESIS_TABLE shape so any change is conscious.

The table IS the algorithm. Adding or removing a bucket should fail this
file's assertions until the test is updated — that's intentional.
"""

from __future__ import annotations

import pytest

from trader.thesis.taxonomy import (
    CONFIDENCE_WEIGHT,
    IGNORE_BUCKETS,
    POLICY_VERSION,
    THESIS_TABLE,
)


def test_policy_version_is_stable_v0():
    """Bumping POLICY_VERSION must be a conscious commit; pinning here."""
    assert POLICY_VERSION == "thesis-table-v0"


def test_table_has_known_buckets():
    """The current taxonomy. Removing or renaming a bucket bumps the version."""
    expected = {
        "fed_dovish_surprise",
        "fed_hawkish_surprise",
        "fomc_minutes_release",
        "cpi_cooler_than_expected",
        "cpi_hotter_than_expected",
        "nfp_strong_miss",
        "nfp_strong_beat",
        "gdp_above_consensus",
        "gdp_below_consensus",
        "geopol_escalation_major",
        "geopol_de_escalation",
        "regulatory_action_megacap",
        "megacap_earnings_beat_and_raise",
        "megacap_earnings_beat_flat_guide",
        "megacap_earnings_miss_or_cut",
        "megacap_mna_target",
        "earnings_season_strong_start",
    }
    assert set(THESIS_TABLE.keys()) == expected


@pytest.mark.parametrize("bucket", list(THESIS_TABLE.keys()))
def test_every_template_has_consistent_shape(bucket):
    t = THESIS_TABLE[bucket]
    assert t.bucket == bucket
    assert t.direction in {"long", "short", "neutral"}
    assert t.confidence in {"low", "medium", "high"}
    assert t.horizon_minutes > 0
    assert t.fade_window_minutes > 0
    assert 0.0 <= t.expected_magnitude_pct < 10.0
    assert len(t.rationale) > 20


def test_ignore_buckets_are_disjoint_from_table():
    """A bucket in IGNORE_BUCKETS must not also be in THESIS_TABLE."""
    assert IGNORE_BUCKETS.isdisjoint(THESIS_TABLE.keys())


def test_confidence_weight_covers_all_levels():
    assert set(CONFIDENCE_WEIGHT.keys()) == {"low", "medium", "high"}
    assert CONFIDENCE_WEIGHT["high"] > CONFIDENCE_WEIGHT["medium"] > CONFIDENCE_WEIGHT["low"] > 0
