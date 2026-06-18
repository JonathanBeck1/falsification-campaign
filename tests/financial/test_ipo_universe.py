"""Unit tests for the IPO-vs-follow-on classifier and SPAC heuristic."""

from __future__ import annotations

from datetime import date

from trader.catalysts.ipo_universe import classify_ipo, is_likely_spac

IPO = date(2024, 6, 1)


def test_classify_true_for_s1_then_no_prior_periodic_report():
    history = [
        ("S-1", date(2024, 2, 1)),
        ("S-1/A", date(2024, 5, 1)),
        ("424B4", IPO),
    ]
    assert classify_ipo(history, IPO) is True


def test_classify_false_when_prior_10k_exists_followon():
    history = [
        ("S-1", date(2020, 1, 1)),
        ("10-K", date(2023, 3, 1)),   # already a reporting company
        ("424B4", IPO),               # this 424B4 is a follow-on
    ]
    assert classify_ipo(history, IPO) is False


def test_classify_false_when_no_registration():
    history = [("424B4", IPO), ("10-Q", date(2023, 8, 1))]
    assert classify_ipo(history, IPO) is False


def test_classify_false_when_s1_too_old():
    history = [("S-1", date(2022, 1, 1)), ("424B4", IPO)]  # >550 days before
    assert classify_ipo(history, IPO) is False


def test_classify_handles_foreign_f1():
    history = [("F-1", date(2024, 3, 1)), ("424B4", IPO)]
    assert classify_ipo(history, IPO) is True


def test_spac_name_detection():
    assert is_likely_spac("Pono Capital Three, Inc.") is False  # 'Capital' alone is not enough
    assert is_likely_spac("Churchill Capital Corp VII") is False  # heuristic is conservative
    assert is_likely_spac("Ajax Acquisition Corp") is True
    assert is_likely_spac("YHN Acquisition I Ltd") is True
    assert is_likely_spac("Vine Hill Capital Investment Corp.") is True
    assert is_likely_spac("Some Blank Check Company") is True
    assert is_likely_spac("Reddit, Inc.") is False
    assert is_likely_spac("Viking Holdings Ltd") is False
    assert is_likely_spac("") is False
