"""Network-free unit tests for the pure CEF resolution classifier + features."""

from __future__ import annotations

from datetime import date

from trader.catalysts.cef_resolution import (
    OUT_DELISTED,
    OUT_DEREGISTERED,
    OUT_MERGER,
    OUT_ONGOING,
    OUT_TENDER,
    classify_resolution,
    classify_sponsor,
    count_amendments,
    extract_features,
    is_municipal_fund,
    is_term_fund,
    resolution_rate,
)

T0 = date(2023, 1, 1)


def _h(*pairs: tuple[str, date]) -> list[tuple[str, date]]:
    return list(pairs)


# --- classify_resolution -----------------------------------------------------


def test_n8f_is_deregistration_resolution():
    hist = _h(("8-K", date(2023, 6, 1)), ("N-8F", date(2023, 9, 1)))
    lab = classify_resolution(hist, T0, has_price_data=False)
    assert lab.outcome == OUT_DEREGISTERED
    assert lab.resolved is True
    assert lab.resolution_date == date(2023, 9, 1)
    assert lab.days_to_resolution == (date(2023, 9, 1) - T0).days


def test_form25_is_delisting_resolution():
    hist = _h(("25-NSE", date(2023, 5, 10)))
    lab = classify_resolution(hist, T0, has_price_data=False)
    assert lab.outcome == OUT_DELISTED
    assert lab.resolved is True
    assert lab.trigger_form == "25-NSE"


def test_merger_forms_resolve():
    hist = _h(("N-14 8C", date(2023, 4, 1)), ("DEFM14A", date(2023, 7, 1)))
    lab = classify_resolution(hist, T0, has_price_data=True)
    assert lab.outcome == OUT_MERGER
    assert lab.resolution_date == date(2023, 4, 1)  # earliest qualifying


def test_deregistration_beats_later_delisting_priority_and_date():
    # N-8F priority over 25 even if 25 filed earlier: dereg wins by priority.
    hist = _h(("25-NSE", date(2023, 3, 1)), ("N-8F", date(2023, 8, 1)))
    lab = classify_resolution(hist, T0, has_price_data=False)
    assert lab.outcome == OUT_DEREGISTERED


def test_bare_tender_with_price_data_is_NOT_resolution():
    # A self-tender while the fund still trades = managed-distribution, not a win.
    hist = _h(("SC TO-I", date(2023, 6, 1)))
    lab = classify_resolution(hist, T0, has_price_data=True)
    assert lab.outcome == OUT_ONGOING
    assert lab.resolved is False


def test_tender_without_price_data_is_resolution():
    hist = _h(("SC TO-I", date(2023, 6, 1)))
    lab = classify_resolution(hist, T0, has_price_data=False)
    assert lab.outcome == OUT_TENDER
    assert lab.resolved is True


def test_no_price_data_no_form_is_delisted_unknown():
    hist = _h(("8-K", date(2023, 2, 1)))
    lab = classify_resolution(hist, T0, has_price_data=False)
    assert lab.outcome == OUT_DELISTED
    assert lab.resolved is True
    assert lab.resolution_date is None
    assert lab.days_to_resolution is None


def test_n23c2_noise_is_ignored():
    # Semiannual term-preferred redemption notices must NOT count as resolution.
    hist = _h(
        ("N-23C-2", date(2023, 4, 1)),
        ("N-23C-2", date(2023, 10, 1)),
        ("N-CSR", date(2023, 12, 1)),
    )
    lab = classify_resolution(hist, T0, has_price_data=True)
    assert lab.outcome == OUT_ONGOING
    assert lab.resolved is False


def test_only_forms_after_filing_date_count():
    # An N-8F BEFORE the 13D cannot be a response to Saba and must be ignored.
    hist = _h(("N-8F", date(2022, 6, 1)), ("8-K", date(2023, 5, 1)))
    lab = classify_resolution(hist, T0, has_price_data=True)
    assert lab.outcome == OUT_ONGOING


def test_clean_ongoing_with_price_data():
    hist = _h(("N-CSR", date(2023, 6, 1)), ("DEF 14A", date(2023, 7, 1)))
    lab = classify_resolution(hist, T0, has_price_data=True)
    assert lab.outcome == OUT_ONGOING
    assert lab.resolved is False
    assert lab.resolution_date is None


def test_def14a_alone_is_not_resolution():
    # Annual proxy alone is not evidence of a terminal event.
    hist = _h(("DEF 14A", date(2023, 9, 1)), ("DEFA14A", date(2023, 9, 5)))
    lab = classify_resolution(hist, T0, has_price_data=True)
    assert lab.resolved is False


# --- features ----------------------------------------------------------------


def test_sponsor_classification():
    assert classify_sponsor("BLACKROCK CALIFORNIA MUNICIPAL INCOME TRUST") == "BlackRock"
    assert classify_sponsor("NUVEEN PENNSYLVANIA QUALITY MUNICIPAL INCOME FUND") == "Nuveen"
    assert classify_sponsor("abrdn Healthcare Investors") == "abrdn"
    assert classify_sponsor("Tortoise Midstream Energy Fund, Inc.") == "Tortoise"
    assert classify_sponsor("Some Unknown Closed End Fund") == "Other"


def test_municipal_detection():
    assert is_municipal_fund("NUVEEN MISSOURI QUALITY MUNICIPAL INCOME FUND") is True
    assert is_municipal_fund("MFS HIGH INCOME MUNICIPAL TRUST") is True
    assert is_municipal_fund("BlackRock Innovation & Growth Trust") is False


def test_term_fund_detection():
    assert is_term_fund("BlackRock Health Sciences Term Trust") is True
    assert is_term_fund("ECOFIN SUSTAINABLE & SOCIAL IMPACT TERM FUND") is True
    assert is_term_fund("NUVEEN CALIFORNIA QUALITY MUNICIPAL INCOME FUND") is False


def test_extract_features_roundtrip():
    f = extract_features(
        "BFZ",
        "0001137391",
        "BLACKROCK CALIFORNIA MUNICIPAL INCOME TRUST",
        date(2023, 3, 6),
        amendment_count=4,
    )
    assert f.sponsor == "BlackRock"
    assert f.is_municipal is True
    assert f.is_term_fund is False
    assert f.is_equity_or_alt is False
    assert f.amendment_count == 4


def test_count_amendments():
    hist = _h(
        ("SC 13D", date(2022, 12, 1)),  # before t0 — ignored
        ("SC 13D/A", date(2023, 2, 1)),
        ("SCHEDULE 13D/A", date(2023, 4, 1)),
        ("SC 13G/A", date(2023, 5, 1)),  # 13G/A is not a 13D amendment
        ("8-K", date(2023, 6, 1)),
    )
    assert count_amendments(hist, T0) == 2


def test_resolution_rate_empty_and_basic():
    assert resolution_rate([]) == 0.0
