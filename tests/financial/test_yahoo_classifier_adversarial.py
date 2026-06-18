"""Adversarial tests for the Yahoo headline classifier.

The substring-match version mislabeled common false-positive phrasings as
fed_commentary / unusual_social_velocity. These tests pin the fix so the
regression can't slip back in.
"""

from __future__ import annotations

import pytest

from trader.normalization.yahoo import classify_yahoo_event_type, classify_yahoo_urgency

# ---------- fed_commentary: should classify ----------


@pytest.mark.parametrize(
    "headline",
    [
        "FOMC statement: rates held at 5.25%",
        "Powell signals patience on inflation",
        "Former Fed Official: rate cuts were a mistake",  # existing dashboard test case
        "Fed minutes show split on rate path",
        "Fed chair Warsh confirmed by Senate",
        "FOMC meeting moves markets",
        "Interest rates cut by 25 basis points after surprise vote",
    ],
)
def test_fed_commentary_true_positives(headline: str):
    assert classify_yahoo_event_type(headline) == "fed_commentary"


def test_fed_commentary_uses_summary_for_disambiguation():
    """Real-world: the headline doesn't say Fed but the summary does. The
    classifier sees title + summary concatenated."""
    headline = "Trump says he'll let Warsh do what he wants to do with interest rates"
    summary = (
        "President Trump shifted his message for the Federal Reserve, "
        "suggesting he'll give some slack to incoming Fed chair Kevin Warsh."
    )
    assert classify_yahoo_event_type(headline, summary) == "fed_commentary"


# ---------- fed_commentary: must NOT classify ----------


@pytest.mark.parametrize(
    "headline",
    [
        "Fed-up customers complain about FedEx delivery delays",  # "fed" present but no monetary context
        "FedEx Q3 earnings beat estimates",  # "FedEx" (no token boundary)
        "Federal Trade Commission sues Microsoft over cloud lock-in",  # "Federal" not "fed"
        "Tax rate cuts to boost growth, says treasury",  # "rate cuts" without "fed/fomc/powell/interest rate"
        "Restaurants raise menu prices as labor rates climb",  # "rates" without fed/interest-rate framing
        "Crime rates drop in Q3",  # bare "rates", no fed context
    ],
)
def test_fed_commentary_false_positives(headline: str):
    assert classify_yahoo_event_type(headline) != "fed_commentary"


# ---------- unusual_social_velocity: should classify ----------


@pytest.mark.parametrize(
    "headline",
    [
        "GameStop short squeeze accelerates",
        "Reddit rally pushes meme stock higher",
        "Trading halt on XYZ after 80% pre-market spike",
        "Unusual options flow detected in NVDA",
    ],
)
def test_social_velocity_true_positives(headline: str):
    assert classify_yahoo_event_type(headline) == "unusual_social_velocity"


# ---------- unusual_social_velocity: must NOT classify ----------


@pytest.mark.parametrize(
    "headline",
    [
        "Options-rich pension plans face new ERISA scrutiny",  # "options" present but not options-flow
        "Top execs weigh options for restructuring",  # generic "options"
        "Momentum stocks outperform in Q3",  # plain "momentum" no longer triggers social velocity
        "Optional 401k matching becomes mandatory",  # "optional", not "options"
    ],
)
def test_social_velocity_false_positives(headline: str):
    assert classify_yahoo_event_type(headline) != "unusual_social_velocity"


# ---------- analyst_upgrade/downgrade: should classify ----------


def test_analyst_upgrade_requires_context():
    assert classify_yahoo_event_type("Morgan Stanley upgrades NVDA to Overweight, raises price target") == "analyst_upgrade"
    assert classify_yahoo_event_type("Goldman Sachs downgrades TSLA; cuts price target to $200") == "analyst_downgrade"
    # Bare "upgrade" without analyst context should NOT count:
    assert classify_yahoo_event_type("iOS 19 upgrade rolls out to iPhone users") != "analyst_upgrade"
    assert classify_yahoo_event_type("Database upgrade slashed query latency") != "analyst_downgrade"


# ---------- urgency parity ----------


def test_fed_commentary_urgency_is_high():
    assert classify_yahoo_urgency("FOMC statement: rates held") == "high"
    assert classify_yahoo_urgency("Fed-up customers complain about FedEx") != "high"  # false-positive guard


def test_social_velocity_urgency_is_high():
    assert classify_yahoo_urgency("GameStop short squeeze accelerates") == "high"
    assert classify_yahoo_urgency("Options-rich pension plans face scrutiny") != "high"


# ---------- existing dashboard expectations (regression guards) ----------


def test_dashboard_existing_cases_still_pass():
    """These exact phrasings are asserted in test_dashboard_data.py — must not regress."""
    assert classify_yahoo_event_type("What Nvidia Earnings Mean for QQQ") == "earnings_surprise"
    assert classify_yahoo_event_type("Former Fed Official: rate cuts were a mistake") == "fed_commentary"
