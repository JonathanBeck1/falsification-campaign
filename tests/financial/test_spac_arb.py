"""Network-free unit tests for the SPAC trust-arb pure logic."""

from __future__ import annotations

from datetime import date

import pytest

from trader.catalysts.spac_arb import (
    SpacListing,
    SpacQuote,
    annualized_yield,
    discount_pct,
    is_predeal_band,
    listings_to_dataframe,
    parse_display_name,
    quotes_to_dataframe,
    summarize_discounts,
)


@pytest.fixture(autouse=True)
def _isolate_env() -> None:
    """Keep this pure module independent of the trading-config fixture."""


# --------------------------------------------------------------------------- #
# parse_display_name
# --------------------------------------------------------------------------- #


def test_parse_display_name_multiple_tickers_takes_common_class() -> None:
    company, ticker, cik = parse_display_name(
        "Black Hawk Acquisition Corp  (BKHA, BKHAR, BKHAU)  (CIK 0002000775)"
    )
    assert company == "Black Hawk Acquisition Corp"
    assert ticker == "BKHA"
    assert cik == "0002000775"


def test_parse_display_name_single_ticker() -> None:
    company, ticker, cik = parse_display_name("Cantor Equity Partners, Inc.  (CEP)  (CIK 0001865602)")
    assert company == "Cantor Equity Partners, Inc."
    assert ticker == "CEP"
    assert cik == "0001865602"


def test_parse_display_name_no_ticker_published() -> None:
    company, ticker, cik = parse_display_name("Tavia Acquisition Corp.  (CIK 0002020385)")
    assert company == "Tavia Acquisition Corp."
    assert ticker is None
    assert cik == "0002020385"


# --------------------------------------------------------------------------- #
# yield math
# --------------------------------------------------------------------------- #


def test_discount_pct_sign_convention() -> None:
    # price below trust -> positive discount (favourable entry)
    assert discount_pct(10.60, 10.00) == pytest.approx(0.06)
    # price above trust -> negative (premium)
    assert discount_pct(10.60, 10.80) == pytest.approx((10.60 - 10.80) / 10.80)


def test_discount_pct_rejects_nonpositive_price() -> None:
    with pytest.raises(ValueError):
        discount_pct(10.60, 0.0)


def test_annualized_yield_compounds_over_holding_period() -> None:
    # 6% raw discount realized over 9 months annualizes above 6%.
    y = annualized_yield(10.60, 10.00, 9.0)
    assert y == pytest.approx((10.60 / 10.00) ** (12.0 / 9.0) - 1.0)
    assert y > 0.06


def test_annualized_yield_at_par_is_zero() -> None:
    assert annualized_yield(10.50, 10.50, 12.0) == pytest.approx(0.0)


def test_annualized_yield_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError):
        annualized_yield(10.60, 0.0, 9.0)
    with pytest.raises(ValueError):
        annualized_yield(10.60, 10.0, 0.0)


# --------------------------------------------------------------------------- #
# pre-deal band filter
# --------------------------------------------------------------------------- #


def test_is_predeal_band_includes_near_trust_excludes_despacs() -> None:
    assert is_predeal_band(10.60) is True
    assert is_predeal_band(9.0) is True
    assert is_predeal_band(13.5) is True
    assert is_predeal_band(8.99) is False  # busted penny de-SPAC
    assert is_predeal_band(42.0) is False  # post-deal operating company


# --------------------------------------------------------------------------- #
# summary
# --------------------------------------------------------------------------- #


def _quote(ticker: str, price: float, trust: float, predeal: bool) -> SpacQuote:
    return SpacQuote(
        ticker=ticker,
        cik=None,
        company=None,
        price=price,
        trust_per_share=trust,
        trust_source="assumed",
        discount_pct=discount_pct(trust, price),
        annualized_yield_pct=annualized_yield(trust, price, 9.0),
        is_predeal_band=predeal,
    )


def test_summarize_discounts_only_counts_predeal_and_splits_discount_premium() -> None:
    quotes = [
        _quote("A", 10.00, 10.60, True),  # discount
        _quote("B", 10.80, 10.60, True),  # premium
        _quote("C", 42.00, 10.60, False),  # de-SPAC, ignored
    ]
    summary = summarize_discounts(quotes)
    assert summary["n_predeal"] == 2.0
    assert summary["n_at_discount"] == 1.0
    assert summary["n_at_premium"] == 1.0
    assert summary["discount_pct_max"] == pytest.approx(discount_pct(10.60, 10.00))


def test_summarize_discounts_empty_when_no_predeal() -> None:
    assert summarize_discounts([_quote("C", 42.0, 10.60, False)]) == {}


# --------------------------------------------------------------------------- #
# dataframes
# --------------------------------------------------------------------------- #


def test_listings_to_dataframe_stable_columns() -> None:
    frame = listings_to_dataframe(
        [SpacListing(ticker="ACME", cik="0001", company="Acme Acquisition Corp.", ipo_date=date(2024, 1, 1))]
    )
    assert list(frame.columns) == ["ticker", "cik", "company", "ipo_date", "source"]
    assert len(frame) == 1
    assert frame.iloc[0]["source"] == "edgar_fts"


def test_quotes_to_dataframe_stable_columns() -> None:
    frame = quotes_to_dataframe([_quote("A", 10.00, 10.60, True)])
    assert list(frame.columns) == [
        "ticker",
        "cik",
        "company",
        "price",
        "trust_per_share",
        "trust_source",
        "discount_pct",
        "annualized_yield_pct",
        "is_predeal_band",
    ]
    assert len(frame) == 1
