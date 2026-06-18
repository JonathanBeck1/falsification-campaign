from __future__ import annotations

from pathlib import Path

from trader import cli


def test_cli_edge_report_writes_report(tmp_path: Path, capsys):
    input_path = tmp_path / "outcomes.md"
    output_path = tmp_path / "edge.md"
    input_path.write_text(
        """# Event Outcome Backtest: SPY

Research-only historical event-outcome analysis.

## Run Metadata

- benchmark: SPY
- entry_time: observed_at
- horizons: 1h
- group_by: event_type, sentiment, urgency

## Coverage

- events_seen: 40
- events_missing_entry_time: 0
- events_with_entry: 40
- missing_entry_bar: 0
- missing_horizon_bar: 0

## Grouped Stats

| group | horizon | n | hit_rate | mean% | median% | stdev% | min% | max% |
|---|---|---|---|---|---|---|---|---|
| event_type=guidance_raise, sentiment=positive, urgency=high | 1h | 40 | 65% | +0.18 | +0.11 | 0.35 | -0.20 | +1.10 |

## Low sample groups

No groups below min_sample=30.
""",
        encoding="utf-8",
    )

    rc = cli.main(
        [
            "edge-report",
            "--outcome-report",
            str(input_path),
            "--output",
            str(output_path),
            "--min-n",
            "30",
            "--cost-bps",
            "2",
        ]
    )

    out = capsys.readouterr().out
    assert rc == 0
    assert f"Edge report written to {output_path}" in out
    report = output_path.read_text(encoding="utf-8")
    assert "# Edge Validation Report" in report
    assert "candidate_edge" in report


def test_cli_edge_report_missing_input_returns_readable_error(tmp_path: Path, capsys):
    missing_path = tmp_path / "missing.md"
    output_path = tmp_path / "edge.md"

    rc = cli.main(["edge-report", "--outcome-report", str(missing_path), "--output", str(output_path)])

    out = capsys.readouterr().out
    assert rc == 1
    assert f"Outcome report not found: {missing_path}" in out
    assert not output_path.exists()


def test_cli_edge_report_invalid_min_n_returns_error(capsys):
    rc = cli.main(["edge-report", "--min-n", "0"])

    out = capsys.readouterr().out
    assert rc == 2
    assert "Invalid edge-report arguments: min_n must be at least 1" in out
