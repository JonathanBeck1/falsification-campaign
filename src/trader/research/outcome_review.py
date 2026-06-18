"""Review generated event outcome backtest reports.

Research-only: this module reads local Markdown reports and produces operator
review notes. It does not fetch data, place orders, or claim trading edge.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class OutcomeStatRow:
    group: str
    horizon: str
    n: int
    hit_rate: float
    mean_return_pct: float
    median_return_pct: float
    stdev_return_pct: float
    min_return_pct: float
    max_return_pct: float


@dataclass(frozen=True)
class LowSampleRow:
    group: str
    horizon: str
    n: int
    min_sample: int


@dataclass(frozen=True)
class OutcomeReportData:
    metadata: dict[str, str] = field(default_factory=dict)
    coverage: dict[str, int] = field(default_factory=dict)
    grouped_stats: list[OutcomeStatRow] = field(default_factory=list)
    low_sample_rows: list[LowSampleRow] = field(default_factory=list)


@dataclass(frozen=True)
class OutcomeGroupReview:
    group: str
    horizon: str
    n: int
    hit_rate: float
    mean_return_pct: float
    verdict: str
    reasons: tuple[str, ...]


@dataclass
class OutcomeReview:
    metadata: dict[str, str]
    coverage: dict[str, int]
    rows: list[OutcomeGroupReview]
    min_sample: int
    focus_horizon: str | None = None
    data_priorities: list[str] = field(default_factory=list)

    @property
    def candidate_rows(self) -> list[OutcomeGroupReview]:
        return [row for row in self.rows if row.verdict == "candidate"]

    @property
    def watchlist_rows(self) -> list[OutcomeGroupReview]:
        return [row for row in self.rows if row.verdict == "watchlist"]

    @property
    def junk_rows(self) -> list[OutcomeGroupReview]:
        return [row for row in self.rows if row.verdict == "junk"]

    @property
    def has_usable_candidates(self) -> bool:
        return bool(self.candidate_rows)

    @property
    def verdict_summary(self) -> str:
        if self.has_usable_candidates:
            return f"{len(self.candidate_rows)} group(s) cleared min_sample={self.min_sample}; review manually before any strategy work."
        return f"Not enough evidence: no non-junk group cleared min_sample={self.min_sample}. Do not infer edge."


def parse_outcome_report(markdown: str) -> OutcomeReportData:
    section_lines = _sections(markdown)
    required = ["Run Metadata", "Coverage", "Grouped Stats", "Low sample groups"]
    missing = [section for section in required if section not in section_lines]
    if missing:
        raise ValueError(f"Missing required section: {missing[0]}")

    metadata = _parse_metadata(section_lines["Run Metadata"])
    coverage = _parse_coverage(section_lines["Coverage"])
    grouped_stats = _parse_grouped_stats(section_lines["Grouped Stats"])
    low_sample_rows = _parse_low_sample_rows(section_lines["Low sample groups"])
    return OutcomeReportData(
        metadata=metadata,
        coverage=coverage,
        grouped_stats=grouped_stats,
        low_sample_rows=low_sample_rows,
    )


def review_outcomes(
    data: OutcomeReportData,
    *,
    min_sample: int,
    focus_horizon: str | None = None,
) -> OutcomeReview:
    if min_sample < 1:
        raise ValueError("min_sample must be at least 1")

    rows: list[OutcomeGroupReview] = []
    for stat in data.grouped_stats:
        if focus_horizon is not None and stat.horizon != focus_horizon:
            continue
        verdict, reasons = _classify_stat(stat, min_sample)
        rows.append(
            OutcomeGroupReview(
                group=stat.group,
                horizon=stat.horizon,
                n=stat.n,
                hit_rate=stat.hit_rate,
                mean_return_pct=stat.mean_return_pct,
                verdict=verdict,
                reasons=tuple(reasons),
            )
        )

    rows.sort(key=_review_sort_key)
    return OutcomeReview(
        metadata=data.metadata,
        coverage=data.coverage,
        rows=rows,
        min_sample=min_sample,
        focus_horizon=focus_horizon,
        data_priorities=_data_priorities(data, rows, min_sample),
    )


def format_outcome_review(review: OutcomeReview) -> str:
    lines = [
        "# Outcome Review",
        "",
        "Research-only second-pass review. This is not trading advice, a live signal, or proof of edge.",
        "",
        "## Verdict",
        "",
        f"- {review.verdict_summary}",
        f"- Events: {review.metadata.get('events', 'unknown')}",
        f"- Missing horizon bars: {review.coverage.get('missing_horizon_bar', 0)}",
        "- Do not infer edge without sufficient sample depth and later cost/slippage checks.",
        "",
        "## Candidate Groups",
        "",
    ]
    lines.extend(_format_rows(review.candidate_rows, empty="No candidate groups cleared the sample and junk filters."))
    lines.extend(["", "## Watchlist Groups", ""])
    lines.extend(_format_rows(review.watchlist_rows, empty="No non-junk low-sample groups to watch."))
    lines.extend(["", "## Junk / Noise", ""])
    lines.extend(_format_rows(review.junk_rows, empty="No ignored or other groups appeared in the parsed stats."))
    lines.extend(["", "## Data Collection Priorities", ""])
    for priority in review.data_priorities:
        lines.append(f"- {priority}")
    lines.extend(["", "## Source Run", ""])
    for key in ("benchmark", "entry_time", "horizons", "group_by", "events", "bars", "source", "event_type"):
        if key in review.metadata:
            lines.append(f"- {key}: {review.metadata[key]}")
    lines.append(f"- min_sample: {review.min_sample}")
    lines.append(f"- focus_horizon: {review.focus_horizon or 'all'}")
    return "\n".join(lines) + "\n"


def _classify_stat(stat: OutcomeStatRow, min_sample: int) -> tuple[str, list[str]]:
    reasons: list[str] = []
    is_junk = "event_type=other" in stat.group or "thesis_bucket=ignored" in stat.group
    if is_junk:
        reasons.append("ignored/other bucket; use for classifier and source-quality feedback")
        return "junk", reasons
    if stat.n < min_sample:
        reasons.append(f"below min_sample={min_sample}")
        return "watchlist", reasons
    reasons.append(f"meets min_sample={min_sample}")
    return "candidate", reasons


def _review_sort_key(row: OutcomeGroupReview) -> tuple[int, int, float, float]:
    verdict_rank = {"candidate": 0, "watchlist": 1, "junk": 2}[row.verdict]
    return (verdict_rank, -row.n, -abs(row.mean_return_pct), -row.hit_rate)


def _data_priorities(data: OutcomeReportData, rows: list[OutcomeGroupReview], min_sample: int) -> list[str]:
    priorities: list[str] = []
    if not any(row.verdict == "candidate" for row in rows):
        priorities.append(f"Collect more events: no non-junk group cleared min_sample={min_sample}.")
    if any("fed_" in row.group or "fed_commentary" in row.group for row in rows):
        priorities.append("Collect more Fed/macro events before evaluating Fed thesis buckets.")
    if any("earnings" in row.group or "guidance" in row.group for row in rows):
        priorities.append("Collect more earnings/guidance events before evaluating single-name drift.")
    if any("event_type=other" in row.group for row in rows):
        priorities.append("Improve classifier/source coverage: event_type=other still dominates part of the sample.")
    if data.coverage.get("missing_horizon_bar", 0) > 0:
        priorities.append("Improve bar coverage: missing horizon bars mean some horizons are incomplete.")
    if not priorities:
        priorities.append("Keep collecting data and compare this review against the next run.")
    return priorities


def _format_rows(rows: list[OutcomeGroupReview], *, empty: str) -> list[str]:
    if not rows:
        return [empty]

    lines = [
        "| group | horizon | n | hit_rate | mean% | verdict | reasons |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        reasons = ", ".join(row.reasons)
        lines.append(
            f"| {_format_table_cell(row.group)} | {_format_table_cell(row.horizon)} | {row.n} | "
            f"{row.hit_rate:.0%} | {row.mean_return_pct:+.2f} | {row.verdict} | "
            f"{_format_table_cell(reasons)} |"
        )
    return lines


def _format_table_cell(value: object) -> str:
    return " ".join(str(value).split()).replace("|", "\\|")


def _sections(markdown: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in markdown.splitlines():
        if line.startswith("## "):
            current = line.removeprefix("## ").strip()
            sections[current] = []
            continue
        if current is not None:
            sections[current].append(line)
    return sections


def _parse_metadata(lines: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in lines:
        if not line.startswith("- ") or ": " not in line:
            continue
        key, value = line.removeprefix("- ").split(": ", 1)
        values[key.strip()] = value.strip()
    return values


def _parse_coverage(lines: list[str]) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in lines:
        if not line.startswith("- ") or ": " not in line:
            continue
        key, value = line.removeprefix("- ").split(": ", 1)
        try:
            values[key.strip()] = int(value.strip())
        except ValueError as exc:
            raise ValueError(f"Invalid coverage value for {key.strip()}: {value.strip()}") from exc
    return values


def _parse_grouped_stats(lines: list[str]) -> list[OutcomeStatRow]:
    rows: list[OutcomeStatRow] = []
    for cells in _table_rows(lines):
        if len(cells) != 9:
            continue
        rows.append(
            OutcomeStatRow(
                group=cells[0],
                horizon=cells[1],
                n=_parse_int(cells[2], "n"),
                hit_rate=_parse_percent(cells[3], "hit_rate"),
                mean_return_pct=_parse_signed_float(cells[4], "mean%"),
                median_return_pct=_parse_signed_float(cells[5], "median%"),
                stdev_return_pct=_parse_signed_float(cells[6], "stdev%"),
                min_return_pct=_parse_signed_float(cells[7], "min%"),
                max_return_pct=_parse_signed_float(cells[8], "max%"),
            )
        )
    return rows


def _parse_low_sample_rows(lines: list[str]) -> list[LowSampleRow]:
    rows: list[LowSampleRow] = []
    for cells in _table_rows(lines):
        if len(cells) != 4:
            continue
        rows.append(
            LowSampleRow(
                group=cells[0],
                horizon=cells[1],
                n=_parse_int(cells[2], "n"),
                min_sample=_parse_int(cells[3], "min_sample"),
            )
        )
    return rows


def _table_rows(lines: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        if stripped.startswith("|---") or stripped.startswith("| group "):
            continue
        cells = [cell.strip() for cell in _split_markdown_table_row(stripped)]
        if cells and cells[0] == "no results":
            continue
        rows.append(cells)
    return rows


def _split_markdown_table_row(row: str) -> list[str]:
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    for char in row.strip("|"):
        if escaped:
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == "|":
            cells.append("".join(current))
            current = []
            continue
        current.append(char)
    cells.append("".join(current))
    return cells


def _parse_int(raw: str, field_name: str) -> int:
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Invalid integer for {field_name}: {raw}") from exc


def _parse_percent(raw: str, field_name: str) -> float:
    if not raw.endswith("%"):
        raise ValueError(f"Invalid percent for {field_name}: {raw}")
    return _parse_signed_float(raw[:-1], field_name) / 100


def _parse_signed_float(raw: str, field_name: str) -> float:
    try:
        return float(raw.replace("+", ""))
    except ValueError as exc:
        raise ValueError(f"Invalid number for {field_name}: {raw}") from exc
