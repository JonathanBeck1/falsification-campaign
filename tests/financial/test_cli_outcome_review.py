from __future__ import annotations

from pathlib import Path

from trader import cli

MINIMAL_OUTCOME_REPORT = """# Event Outcome Backtest: SPY

## Run Metadata

- benchmark: SPY
- entry_time: observed_at
- horizons: 5m, 15m
- group_by: event_type, sentiment, urgency, thesis_bucket
- bars: 79
- data_provider: yahoo
- event_type: all
- events: 12
- minutes: 5
- source: all

## Coverage

- events_seen: 12
- events_missing_entry_time: 0
- events_with_entry: 12
- missing_entry_bar: 0
- missing_horizon_bar: 0

## Grouped Stats

| group | horizon | n | hit_rate | mean% | median% | stdev% | min% | max% |
|---|---|---|---|---|---|---|---|---|
| event_type=fed_commentary, sentiment=neutral, urgency=high, thesis_bucket=fomc_minutes_release | 15m | 12 | 67% | +0.20 | +0.10 | 0.30 | -0.10 | +0.80 |
| event_type=other, sentiment=neutral, urgency=normal, thesis_bucket=ignored | 5m | 4 | 50% | +0.01 | +0.01 | 0.02 | -0.02 | +0.04 |

## Low sample groups

| group | horizon | n | min_sample |
|---|---|---|---|
| event_type=other, sentiment=neutral, urgency=normal, thesis_bucket=ignored | 5m | 4 | 10 |
"""


def test_cli_outcome_review_writes_markdown_report(tmp_path: Path, capsys):
    input_path = tmp_path / "outcomes.md"
    output_path = tmp_path / "review.md"
    input_path.write_text(MINIMAL_OUTCOME_REPORT)

    rc = cli.main(
        [
            "outcome-review",
            "--outcome-report",
            str(input_path),
            "--output",
            str(output_path),
            "--min-sample",
            "10",
        ]
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert f"Outcome review written to {output_path}" in out
    review = output_path.read_text()
    assert "# Outcome Review" in review
    assert "## Candidate Groups" in review
    assert "fomc_minutes_release" in review


def test_cli_outcome_review_missing_input_returns_readable_error(tmp_path: Path, capsys):
    missing_path = tmp_path / "missing.md"
    output_path = tmp_path / "review.md"

    rc = cli.main(["outcome-review", "--outcome-report", str(missing_path), "--output", str(output_path)])

    out = capsys.readouterr().out
    assert rc == 1
    assert f"Outcome report not found: {missing_path}" in out
    assert not output_path.exists()


def test_cli_outcome_review_invalid_min_sample_returns_error(capsys):
    rc = cli.main(["outcome-review", "--min-sample", "0"])

    out = capsys.readouterr().out
    assert rc == 2
    assert "Invalid outcome-review arguments: min_sample must be at least 1" in out


def test_cli_outcome_review_focus_horizon_limits_output(tmp_path: Path):
    input_path = tmp_path / "outcomes.md"
    output_path = tmp_path / "review.md"
    input_path.write_text(MINIMAL_OUTCOME_REPORT)

    rc = cli.main(
        [
            "outcome-review",
            "--outcome-report",
            str(input_path),
            "--output",
            str(output_path),
            "--focus-horizon",
            "5m",
        ]
    )

    assert rc == 0
    review = output_path.read_text()
    assert "focus_horizon: 5m" in review
    assert "fomc_minutes_release" not in review
    assert "thesis_bucket=ignored" in review
