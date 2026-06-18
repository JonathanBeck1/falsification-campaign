"""Tests for the campaign scoreboard parser (scripts/build_campaign_scoreboard.py).

The parser turns brain/34's registry markdown into structured rows. These tests
pin its handling of the registry's real line shapes (verdict form, planned
'*Mech: ...*' form, multi-line wraps, em-dash-inside-italic, trailing
parenthetical) so a format wobble surfaces as a failing test, not a silently
wrong results table.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_campaign_scoreboard.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("build_campaign_scoreboard", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # so @dataclass can resolve the module
    spec.loader.exec_module(mod)
    return mod


sb = _load_module()


# --------------------------------------------------------------------------- #
# name/result split
# --------------------------------------------------------------------------- #
def test_split_verdict_form():
    name, result = sb._split_name_result("Turn-of-month effect — *KILL: +3.4 bps/day gross.*")
    assert name == "Turn-of-month effect"
    assert result == "KILL: +3.4 bps/day gross."


def test_split_planned_mech_form():
    name, result = sb._split_name_result(
        "Opening vol-crush / intraday vol-of-vol. *Mech: systematic AM IV decay.*"
    )
    assert name == "Opening vol-crush / intraday vol-of-vol"
    assert result == "Mech: systematic AM IV decay."


def test_split_em_dash_inside_italic():
    # T22: an em-dash lives INSIDE the result; it must not split the name early.
    name, result = sb._split_name_result(
        "Index dispersion / correlation premium (index IV rich vs constituents). "
        "*Mech: structurally capacity-limited — expensive to harvest.*"
    )
    assert name == "Index dispersion / correlation premium (index IV rich vs constituents)"
    assert "expensive to harvest" in result


def test_split_trailing_parenthetical_after_italic():
    # T38: a parenthetical follows the italic; result is the italic, not the tail.
    name, result = sb._split_name_result(
        "COT positioning signal. *Mech: commercial vs spec imbalance.* "
        "(Continuous-contract construction = a data-quality trap; control the roll.)"
    )
    assert name == "COT positioning signal"
    assert result == "Mech: commercial vs spec imbalance."


def test_split_no_italic_is_all_name():
    name, result = sb._split_name_result("Some bare planned test with no blurb")
    assert name == "Some bare planned test with no blurb"
    assert result == ""


# --------------------------------------------------------------------------- #
# verdict classification
# --------------------------------------------------------------------------- #
def test_classify_no_edge():
    assert sb.classify_verdict("done", "no edge (every config lost)") == "no-edge"


def test_classify_kill():
    assert sb.classify_verdict("done", "KILL (composition)") == "kill"
    assert sb.classify_verdict("done", "LOOK-AHEAD KILL") == "kill"


def test_classify_data_wall():
    # A genuine DATA_WALL verdict (couldn't measure the edge — data failed) is
    # ⛔-marked (merged status) with the verdict label at the start of the blurb.
    assert sb.classify_verdict("merged", "data_wall: easy-to-borrow mega-caps...") == "data-wall"
    assert sb.classify_verdict("merged", "DATA_WALL: completed-deal targets delist...") == "data-wall"
    # T06's "DATA KILL (parity-derived)" is a KILL (edge falsified as a data
    # glitch), NOT an untestable data-wall.
    assert sb.classify_verdict("done", "DATA KILL (parity-derived)") == "kill"
    # A null that merely mentions "no data wall" (T42) must NOT be a data-wall.
    assert sb.classify_verdict("done", "KILL: decayed null ... well-powered, no data wall.") == "kill"
    # A true ⛔ MERGED (no-padding dup) stays merged.
    assert sb.classify_verdict("merged", "MERGED into T29 (no-padding): perp basis ...") == "merged"


def test_classify_split_spot_mention_is_not_marginal():
    # T23/T25 KILLs mention the "split-spot bug" — must NOT trip the marginal
    # bucket (the bare substring "split" used to mislabel them).
    assert sb.classify_verdict("done", "KILL: ... immune to the split-spot bug.") == "kill"
    assert sb.classify_verdict("done", "KILL: ... was a split-spot artifact (removed).") == "kill"


def test_classify_marginal_emoji_overrides_kill_in_text():
    # T32: blurb says SPLIT/MARGINAL ... ETH KILLED; the 🟡 marker wins.
    v = sb.classify_verdict("done", "SPLIT/MARGINAL ... ETH KILLED (OOS sign-flip).", emoji="🟡")
    assert v == "marginal"


def test_classify_marginal_from_text():
    assert sb.classify_verdict("done", "bounded, uncapturable") == "marginal"
    assert sb.classify_verdict("done", "MARGINAL FAIL") == "marginal"


def test_classify_artifact_is_kill():
    assert sb.classify_verdict("done", "4 baseline artifacts") == "kill"


def test_classify_status_buckets():
    assert sb.classify_verdict("planned", "Mech: whatever") == "planned"
    assert sb.classify_verdict("in-flight", "data backfilling") == "in-flight"
    assert sb.classify_verdict("merged", "MERGED into T29") == "merged"


# --------------------------------------------------------------------------- #
# full parse of a synthetic registry block
# --------------------------------------------------------------------------- #
SAMPLE = """\
# Master registry

## A. Index options — QQQ (owned 💾)
- ✅ **T01** Intraday sweep — *no edge* (every config lost).
- ✅ **T19** VRP daily condor — *KILL, mechanism null*.

## D. Crypto — 24/7 (🆓)
- 🟡 **T32** Crypto VRP (DVOL) — *SPLIT/MARGINAL, most-alive. ETH KILLED.*
- ⛔ **T30** Spot-perp basis — *MERGED into T29.*

## E. Futures (💲)
- ⬜ **T22** Index dispersion (index IV rich vs
  constituents). *Mech: capacity-limited — expensive to harvest.*
- 🔄 **T20** 0DTE short-premium — *data backfilling*.
"""


def test_parse_sample_counts_and_categories():
    entries = sb.parse_registry(SAMPLE)
    assert len(entries) == 6
    by_id = {e.test_id: e for e in entries}

    assert by_id["T01"].verdict == "no-edge"
    assert by_id["T01"].category == "Index options"
    assert by_id["T19"].verdict == "kill"
    assert by_id["T32"].verdict == "marginal"   # 🟡 despite "ETH KILLED"
    assert by_id["T32"].category == "Crypto"
    assert by_id["T30"].verdict == "merged"
    assert by_id["T20"].verdict == "in-flight"

    # multi-line wrap stitched + em-dash-in-italic handled
    t22 = by_id["T22"]
    assert t22.verdict == "planned"
    assert t22.name == "Index dispersion (index IV rich vs constituents)"
    assert "expensive to harvest" in t22.result


def test_tally_on_sample():
    entries = sb.parse_registry(SAMPLE)
    counts = sb.tally(entries)
    assert counts["no-edge"] == 1
    assert counts["kill"] == 1
    assert counts["marginal"] == 1
    assert counts["merged"] == 1
    assert counts["in-flight"] == 1
    assert counts["planned"] == 1


def test_render_scoreboard_is_markdown_table():
    entries = sb.parse_registry(SAMPLE)
    md = sb.render_scoreboard(entries)
    assert "# Campaign Scoreboard" in md
    assert "| id | category | name | verdict | result |" in md
    assert "T32" in md and "MARGINAL" in md
    # tally headline present
    assert "negative verdict" in md


def test_tally_text_round_trips():
    entries = sb.parse_registry(SAMPLE)
    text = sb.tally_text(entries)
    assert "total=6" in text
    assert "marginal=1" in text


# --------------------------------------------------------------------------- #
# live registry: parser must consume the real file cleanly
# --------------------------------------------------------------------------- #
def test_live_registry_parses_all_tests():
    registry = _SCRIPT.resolve().parents[1] / "brain" / "34_master_test_registry.md"
    if not registry.exists():
        pytest.skip("registry not present")
    entries = sb.parse_registry(registry.read_text(encoding="utf-8"))
    ids = sorted(e.id_num for e in entries)
    # contiguous T01..TN, no duplicates, no gaps
    assert ids == list(range(1, len(ids) + 1)), ids
    # every tested row got a non-empty result blurb
    for e in entries:
        if e.status == "done":
            assert e.result, f"{e.test_id} has empty result"
