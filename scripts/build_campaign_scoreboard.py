#!/usr/bin/env python
"""Build the campaign scoreboard from brain/34_master_test_registry.md.

The registry is the campaign's source of truth: one bullet per test, with a
status emoji, a `**T##**` id, a name, and an italic *result* blurb. This script
parses every test line (robust to the multi-line wraps the registry uses) and
emits ``research/CAMPAIGN_SCOREBOARD.md`` — the single clean results table that
becomes the research paper's main results table — plus tallies and a
by-category breakdown.

It does NOT edit the registry (read-only). Run live; commit the generated
scoreboard separately.

Usage:
    python scripts/build_campaign_scoreboard.py            # write the scoreboard
    python scripts/build_campaign_scoreboard.py --check    # just print the tally
    python scripts/build_campaign_scoreboard.py --stdout   # print, don't write

Registry line grammar (examples this parser handles):
    - ✅ **T48** Turn-of-month effect — *KILL: +3.4 bps/day gross ...*
    - ⬜ **T27** 0DTE dealer-gamma-conditioned intraday reversion. *Mech: ...
      continues on the next indented line.*
    - 🔄 **T20** 0DTE short-premium (defined-risk, mechanical) — *data backfilling*.
    - ⛔ **T30** Spot-perp basis — *MERGED into T29 ...*
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "brain" / "34_master_test_registry.md"
SCOREBOARD = ROOT / "research" / "CAMPAIGN_SCOREBOARD.md"

# Status emojis the registry uses, mapped to a human status.
STATUS_EMOJI = {
    "✅": "done",
    "🟡": "done",       # marginal results are tested -> done
    "⛔": "merged",
    "🔄": "in-flight",
    "⬜": "planned",
}
# 🟡 is the registry's dedicated "marginal" marker — it overrides text parsing
# (a marginal blurb often also mentions a killed sub-arm, e.g. T32 "ETH KILLED").
MARGINAL_EMOJI = "🟡"

# A test bullet: "- <emoji> **T##** <rest...>"
TEST_RE = re.compile(r"^-\s+(?P<emoji>[✅🟡⛔🔄⬜])\s+\*\*(?P<id>T\d+)\*\*\s*(?P<rest>.*)$")
# A category header: "## A. Index options / volatility — QQQ (...)"
CATEGORY_RE = re.compile(r"^##\s+(?P<letter>[A-Z])\.\s+(?P<name>.+?)\s*(?:\(.*\))?\s*$")
# A continuation line: indented, not a new bullet/header.
CONT_RE = re.compile(r"^\s{2,}\S")


@dataclass
class TestEntry:
    test_id: str
    id_num: int
    status: str          # done / in-flight / planned / merged
    category: str        # e.g. "Seasonality / calendar"
    name: str
    result: str          # the italic blurb (verdict + one-liner), trimmed
    verdict: str         # normalized verdict bucket


# Verdict buckets (the paper's columns). Order matters: first match wins.
def classify_verdict(status: str, result: str, emoji: str = "") -> str:
    """Map a test's status + result blurb (+ emoji) to a verdict bucket."""
    text = result.lower()
    if status == "planned":
        return "planned"
    if status == "in-flight":
        return "in-flight"
    # ⛔ is OVERLOADED in the registry: a true MERGED no-padding duplicate (T30)
    # vs a DATA_WALL (a tested family whose edge could not be measured because the
    # data itself failed — T26 wrong universe, T40 inverse survivorship). The
    # STATUS_EMOJI map sends both to "merged"; disambiguate by the blurb text.
    if status == "merged":
        # match the VERDICT LABEL at the start of the blurb, not any mention of
        # "data wall" (T42's null says "...no data wall", which is NOT one).
        if text.startswith("data_wall") or text.startswith("data wall"):
            return "data-wall"
        return "merged"

    # marginal / bounded / uncapturable — alive-but-not-claimable. The 🟡 marker
    # is authoritative (a marginal blurb often also names a killed sub-arm, e.g.
    # T32 "SPLIT/MARGINAL ... ETH KILLED"). Do NOT match the bare substring
    # "split": it appears in "split-spot bug" mentions in T23/T25, which are KILLs.
    if emoji == MARGINAL_EMOJI or any(
        k in text for k in ("marginal", "bounded", "uncapturable")
    ):
        return "marginal"
    # data-wall on a ✅-marked row explicitly labeled DATA_WALL (defensive; the
    # current data-walls T26/T40 are ⛔ and handled above).
    if text.startswith("data_wall") or text.startswith("data wall"):
        return "data-wall"
    # kills — incl. look-ahead / decayed / artifact and the derived-fake-data
    # "DATA KILL" (T06): the strategy WAS tested and its edge falsified as a data
    # glitch, which is a kill of the claim, not an untestable data-wall.
    if "kill" in text:
        return "kill"
    # explicit "no edge"
    if "no edge" in text:
        return "no-edge"
    # 4 baseline artifacts (Phase 2): an artifact finding == a kill of the claim
    if "artifact" in text:
        return "kill"
    # fallthrough for a tested row with an unrecognized blurb
    return "tested-other"


VERDICT_LABEL = {
    "kill": "KILL",
    "no-edge": "NO EDGE",
    "data-wall": "DATA WALL",
    "marginal": "MARGINAL",
    "tested-other": "TESTED",
    "in-flight": "IN-FLIGHT",
    "planned": "PLANNED",
    "merged": "MERGED",
}


# The result blurb: the first *italic* span. Non-greedy, allows the em-dash and
# parentheses that appear *inside* result text (e.g. T22's "— expensive to
# harvest", T32's long blurb). ``**bold**`` is excluded so a stray bold token
# isn't mistaken for the italic result.
ITALIC_RE = re.compile(r"(?<!\*)\*([^*].*?)\*(?!\*)", re.DOTALL)


def _split_name_result(rest: str) -> tuple[str, str]:
    """Split a test bullet's body into (name, result-blurb).

    The result is the FIRST single-* italic span anywhere in the body; the name
    is the text before it (with a trailing em-dash or period stripped). This is
    robust to:
      * em-dashes *inside* the italic (T22: "...— expensive to harvest.*"),
      * a trailing parenthetical *after* the italic (T38: "*Mech: ...* (Cont...)"),
      * the plain "Name — *KILL: ...*" verdict form.
    Falls back to the em-dash split, then to the whole string as the name, when
    no italic is present.
    """
    rest = re.sub(r"\s+", " ", rest).strip()
    m = ITALIC_RE.search(rest)
    if m:
        name = rest[: m.start()].strip()
        # strip a trailing separator (em-dash or period) left on the name
        name = re.sub(r"\s*[—-]\s*$", "", name).rstrip(".").strip()
        result = re.sub(r"\s+", " ", m.group(1)).strip()
        return name, result
    # no italic: fall back to em-dash split
    if " — " in rest:
        name, tail = rest.split(" — ", 1)
        return name.strip().rstrip("."), tail.strip().strip(".")
    return rest.rstrip("."), ""


def parse_registry(text: str) -> list[TestEntry]:
    """Parse the registry markdown into TestEntry rows, in file order."""
    lines = text.splitlines()
    entries: list[TestEntry] = []
    current_category = "(uncategorized)"
    i = 0
    while i < len(lines):
        line = lines[i]
        cat_m = CATEGORY_RE.match(line)
        if cat_m and not TEST_RE.match(line):
            # Category names contain an em-dash before the data-tier note; keep
            # only the strategy-family part for a clean column.
            name = cat_m.group("name").split(" — ")[0].strip()
            current_category = name
            i += 1
            continue

        test_m = TEST_RE.match(line)
        if test_m:
            # Gather continuation lines (indented, not a new bullet/header).
            rest = test_m.group("rest")
            j = i + 1
            while j < len(lines) and CONT_RE.match(lines[j]) and not TEST_RE.match(lines[j]):
                rest += " " + lines[j].strip()
                j += 1
            name, result = _split_name_result(rest)
            emoji = test_m.group("emoji")
            status = STATUS_EMOJI[emoji]
            verdict = classify_verdict(status, result, emoji)
            entries.append(
                TestEntry(
                    test_id=test_m.group("id"),
                    id_num=int(test_m.group("id")[1:]),
                    status=status,
                    category=current_category,
                    name=name,
                    result=result,
                    verdict=verdict,
                )
            )
            i = j
            continue
        i += 1
    return entries


def tally(entries: list[TestEntry]) -> Counter:
    """Count entries by verdict bucket."""
    return Counter(e.verdict for e in entries)


def _one_line(result: str, limit: int = 160) -> str:
    """Trim a result blurb to one clean table-cell line."""
    r = result.replace("|", "\\|").strip()
    if len(r) > limit:
        r = r[: limit - 1].rstrip() + "…"
    return r


def render_scoreboard(entries: list[TestEntry]) -> str:
    counts = tally(entries)
    tested = sum(
        counts[v] for v in ("kill", "no-edge", "data-wall", "marginal", "tested-other")
    )
    kills = counts["kill"]
    no_edge = counts["no-edge"]
    data_walls = counts["data-wall"]
    marginals = counts["marginal"]
    in_flight = counts["in-flight"]
    planned = counts["planned"]
    merged = counts["merged"]
    total = len(entries)

    lines: list[str] = []
    lines.append("# Campaign Scoreboard — master results table")
    lines.append("")
    lines.append(
        "Auto-generated from `brain/34_master_test_registry.md` by "
        "`scripts/build_campaign_scoreboard.py`. Do not edit by hand — re-run the "
        "generator. This is the research paper's main results table."
    )
    lines.append("")
    lines.append("## Tally")
    lines.append("")
    lines.append("| metric | count |")
    lines.append("|---|---:|")
    lines.append(f"| Total tests in registry | {total} |")
    lines.append(f"| **Tested (verdict reached)** | **{tested}** |")
    lines.append(f"| &nbsp;&nbsp;— Kills | {kills} |")
    lines.append(f"| &nbsp;&nbsp;— No-edge | {no_edge} |")
    lines.append(f"| &nbsp;&nbsp;— Marginal / split | {marginals} |")
    lines.append(f"| &nbsp;&nbsp;— Data-wall | {data_walls} |")
    if counts["tested-other"]:
        lines.append(f"| &nbsp;&nbsp;— Tested (other) | {counts['tested-other']} |")
    lines.append(f"| In-flight | {in_flight} |")
    lines.append(f"| Planned | {planned} |")
    lines.append(f"| Merged / folded | {merged} |")
    lines.append("")
    negative = kills + no_edge + data_walls
    if tested:
        lines.append(
            f"**Headline:** {negative}/{tested} tested strategies reached a negative "
            f"verdict (kill / no-edge / data-wall); {marginals} marginal "
            f"(alive but not claimable). {in_flight} in-flight, {planned} planned."
        )
        lines.append("")

    # By-category breakdown
    lines.append("## By category")
    lines.append("")
    lines.append("| category | tested | kills | no-edge | marginal | data-wall | in-flight | planned |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    seen: list[str] = []
    for e in entries:
        if e.category not in seen:
            seen.append(e.category)
    for cat in seen:
        ce = [e for e in entries if e.category == cat]
        cc = Counter(e.verdict for e in ce)
        c_tested = sum(
            cc[v] for v in ("kill", "no-edge", "data-wall", "marginal", "tested-other")
        )
        lines.append(
            f"| {cat} | {c_tested} | {cc['kill']} | {cc['no-edge']} | "
            f"{cc['marginal']} | {cc['data-wall']} | {cc['in-flight']} | {cc['planned']} |"
        )
    lines.append("")

    # Full results table
    lines.append("## Results")
    lines.append("")
    lines.append("| id | category | name | verdict | result |")
    lines.append("|---|---|---|---|---|")
    for e in sorted(entries, key=lambda x: x.id_num):
        label = VERDICT_LABEL.get(e.verdict, e.verdict.upper())
        lines.append(
            f"| {e.test_id} | {e.category} | {_one_line(e.name, 70)} | "
            f"{label} | {_one_line(e.result)} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def tally_text(entries: list[TestEntry]) -> str:
    counts = tally(entries)
    tested = sum(
        counts[v] for v in ("kill", "no-edge", "data-wall", "marginal", "tested-other")
    )
    parts = [
        f"total={len(entries)}",
        f"tested={tested}",
        f"kills={counts['kill']}",
        f"no-edge={counts['no-edge']}",
        f"marginal={counts['marginal']}",
        f"data-wall={counts['data-wall']}",
        f"in-flight={counts['in-flight']}",
        f"planned={counts['planned']}",
        f"merged={counts['merged']}",
    ]
    if counts["tested-other"]:
        parts.append(f"tested-other={counts['tested-other']}")
    return "  ".join(parts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="print the tally only, do not write")
    ap.add_argument("--stdout", action="store_true", help="print the scoreboard, do not write")
    ap.add_argument("--registry", type=Path, default=REGISTRY, help="path to the registry md")
    ap.add_argument("--out", type=Path, default=SCOREBOARD, help="output scoreboard path")
    args = ap.parse_args(argv)

    if not args.registry.exists():
        print(f"ERROR: registry not found: {args.registry}", file=sys.stderr)
        return 2

    entries = parse_registry(args.registry.read_text(encoding="utf-8"))
    if not entries:
        print("ERROR: parsed 0 test entries — registry format may have changed", file=sys.stderr)
        return 3

    if args.check:
        print(tally_text(entries))
        return 0

    md = render_scoreboard(entries)
    if args.stdout:
        print(md)
        return 0

    args.out.write_text(md, encoding="utf-8")
    print(f"wrote {args.out} ({len(entries)} tests)")
    print(tally_text(entries))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
