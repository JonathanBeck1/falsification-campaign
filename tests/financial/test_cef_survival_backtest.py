"""Synthetic, network-free tests for the CEF discount-capture survival backtest.

Prices are built by hand so the realized excess return is known exactly. The
price provider is a dict-backed stub (no yfinance / Tiingo / network).
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from trader.catalysts.cef_survival_backtest import (
    Campaign,
    aggregate_basket,
    compute_campaign_return,
    evaluate_gate,
    is_tilted,
    run_backtest,
)


def _series(start: str, n: int, level: float, name: str) -> pd.Series:
    idx = pd.bdate_range(start, periods=n)
    return pd.Series([level] * n, index=idx, name=name)


def _ramp(start: str, n: int, p0: float, p1: float, name: str) -> pd.Series:
    idx = pd.bdate_range(start, periods=n)
    vals = [p0 + (p1 - p0) * i / (n - 1) for i in range(n)]
    return pd.Series(vals, index=idx, name=name)


# --- compute_campaign_return (pure) ------------------------------------------


def test_resolved_excess_capture_is_recovered():
    # Target +20% to resolution; benchmark +5% over same span => +15% excess.
    tgt = _ramp("2023-01-02", 260, 100.0, 120.0, "RES")
    bench = _ramp("2023-01-02", 260, 100.0, 105.0, "PCEF")
    r = compute_campaign_return(
        tgt,
        bench,
        ticker="RES",
        filing_date=date(2023, 1, 1),
        resolved=True,
        resolution_date=date(2023, 12, 29),
        today=date(2026, 1, 1),
    )
    assert r is not None
    assert r.priced and r.resolved
    assert r.target_return == pytest.approx(0.20, rel=1e-2)
    assert r.bench_return == pytest.approx(0.05, rel=1e-2)
    assert r.excess_return == pytest.approx(0.15, rel=1e-2)
    assert r.excess_annualized > 0


def test_ongoing_campaign_uses_capped_hold():
    # No resolution date => exit capped at min(today, filing+max_hold).
    tgt = _series("2023-01-02", 400, 100.0, "ONG")
    bench = _series("2023-01-02", 400, 100.0, "PCEF")
    r = compute_campaign_return(
        tgt,
        bench,
        ticker="ONG",
        filing_date=date(2023, 1, 1),
        resolved=False,
        resolution_date=None,
        today=date(2026, 1, 1),
        max_hold_days=200,
    )
    assert r is not None
    assert r.note == "censored-cap"
    # Flat target & benchmark => zero excess.
    assert r.excess_return == pytest.approx(0.0, abs=1e-9)
    # Hold capped near 200 calendar days, not the full series.
    assert r.holding_days <= 200


def test_exit_takes_last_quote_before_delisting_gap():
    # Target stops trading well before the (later) resolution date — exit must use
    # the last available quote, not fail.
    tgt = _ramp("2023-01-02", 120, 100.0, 130.0, "GAP")  # ~6 months of data
    bench = _series("2023-01-02", 800, 100.0, "PCEF")
    r = compute_campaign_return(
        tgt,
        bench,
        ticker="GAP",
        filing_date=date(2023, 1, 1),
        resolved=True,
        resolution_date=date(2024, 12, 1),  # far after last target quote
        today=date(2026, 1, 1),
    )
    assert r is not None
    assert r.target_return == pytest.approx(0.30, rel=1e-2)


def test_returns_none_when_no_entry_available():
    # Filing after the series ends => no entry day.
    tgt = _series("2020-01-02", 50, 100.0, "OLD")
    bench = _series("2020-01-02", 50, 100.0, "PCEF")
    r = compute_campaign_return(
        tgt,
        bench,
        ticker="OLD",
        filing_date=date(2025, 1, 1),
        resolved=False,
        resolution_date=None,
        today=date(2026, 1, 1),
    )
    assert r is None


# --- tilt selection ----------------------------------------------------------


def _camp(ticker, sponsor, muni) -> Campaign:
    return Campaign(
        ticker=ticker,
        name=ticker,
        filing_date=date(2023, 1, 1),
        sponsor=sponsor,
        is_municipal=muni,
        resolved=True,
        resolution_date=date(2023, 12, 29),
    )


def test_tilt_keeps_muni_and_fast_sponsor_drops_slow_equity():
    assert is_tilted(_camp("A", "MFS", muni=False))          # fast sponsor
    assert is_tilted(_camp("B", "Nuveen", muni=True))        # muni at slow-ish sponsor kept
    assert is_tilted(_camp("C", "abrdn", muni=True))         # muni overrides slow sponsor
    assert not is_tilted(_camp("D", "Invesco", muni=False))  # slow equity dropped
    assert not is_tilted(_camp("E", "Other", muni=False))    # neither muni nor fast


# --- aggregation -------------------------------------------------------------


def test_aggregate_basket_stats():
    tgt_up = _ramp("2023-01-02", 260, 100.0, 120.0, "U")
    bench = _ramp("2023-01-02", 260, 100.0, 105.0, "PCEF")
    rets = []
    for tk in ("U1", "U2", "U3"):
        r = compute_campaign_return(
            tgt_up, bench, ticker=tk, filing_date=date(2023, 1, 1),
            resolved=True, resolution_date=date(2023, 12, 29), today=date(2026, 1, 1),
        )
        assert r is not None
        rets.append(r)
    stat = aggregate_basket(rets, label="x")
    assert stat.n == 3
    assert stat.mean_excess == pytest.approx(0.15, rel=1e-2)
    assert stat.pct_positive == 1.0


# --- run_backtest (with stub provider) + gate --------------------------------


class _StubProvider:
    def __init__(self, table: dict[str, pd.Series]):
        self.table = table

    def __call__(self, ticker, start, end):
        return self.table.get(ticker)


def test_run_backtest_tilt_beats_untilted_and_gate_passes():
    bench = _ramp("2023-01-02", 300, 100.0, 105.0, "PCEF")
    # 20 muni winners (+25% each) + 6 equity-at-slow-sponsor flats.
    table: dict[str, pd.Series] = {"PCEF": bench}
    campaigns: list[Campaign] = []
    for i in range(20):
        tk = f"MUNI{i}"
        table[tk] = _ramp("2023-01-02", 300, 100.0, 125.0, tk)
        campaigns.append(Campaign(tk, tk, date(2023, 1, 1), "MFS", True, True, date(2023, 12, 29)))
    for i in range(6):
        tk = f"EQ{i}"
        table[tk] = _ramp("2023-01-02", 300, 100.0, 105.0, tk)  # tracks bench => ~0 excess
        campaigns.append(Campaign(tk, tk, date(2023, 1, 1), "Invesco", False, False, date(2023, 12, 29)))

    result = run_backtest(campaigns, _StubProvider(table), today=date(2026, 1, 1))
    assert result.n_priced == 26
    assert result.tilted.n == 20  # only the muni names survive the tilt
    assert result.tilted.mean_excess > result.untilted.mean_excess
    verdict = evaluate_gate(result)
    assert verdict.passed, verdict.reasons


def test_run_backtest_records_unpriced_names():
    bench = _series("2023-01-02", 300, 100.0, "PCEF")
    table = {"PCEF": bench, "ALIVE": _series("2023-01-02", 300, 100.0, "ALIVE")}
    campaigns = [
        Campaign("ALIVE", "ALIVE", date(2023, 1, 1), "MFS", True, False, None),
        Campaign("DELISTED", "DELISTED", date(2023, 1, 1), "MFS", True, True, date(2023, 12, 29)),
    ]
    result = run_backtest(campaigns, _StubProvider(table), today=date(2026, 1, 1))
    assert result.n_priced == 1
    notes = {r.ticker: r.note for r in result.per_campaign}
    assert notes["DELISTED"] == "no-price-data"


def test_gate_fails_without_enough_priced_names():
    bench = _series("2023-01-02", 300, 100.0, "PCEF")
    table = {"PCEF": bench, "ONE": _ramp("2023-01-02", 300, 100.0, 130.0, "ONE")}
    campaigns = [Campaign("ONE", "ONE", date(2023, 1, 1), "MFS", True, True, date(2023, 12, 29))]
    result = run_backtest(campaigns, _StubProvider(table), today=date(2026, 1, 1))
    verdict = evaluate_gate(result)
    assert not verdict.passed
    assert any("priced N=" in r and "FAIL" in r for r in verdict.reasons)
