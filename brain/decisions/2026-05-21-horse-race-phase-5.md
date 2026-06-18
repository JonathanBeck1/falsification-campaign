# Horse-Race Phase 5: Leaderboard Command

## Decision

Add a `trader-daily leaderboard` CLI command that reads the
`brain_equity_curve` table, computes risk-adjusted performance metrics
for every brain that has equity data, and prints a sorted leaderboard
to stdout (with optional Markdown export). This is the **actual horse-race
output** — the verdict the user needs after running the 19-brain matrix
for some number of market days.

Phase 5 of the 5-phase horse race plan. After Phase 5 lands, the horse
race has both inputs (brains writing equity) and outputs (leaderboard
ranking them).

## Why

- Phases 1-4 will deposit equity-curve data for 19 brains every cycle.
  Without a ranking command, that data sits in SQLite and the user
  has to write ad-hoc queries to compare.
- The leaderboard makes the **risk-profile dial AND LLM model axis**
  visible side-by-side, which is the whole point of running a horse race.
- Phase 5 produces a **paper-trading verdict**, NOT M4 backtest evidence.
  Display thresholds explicitly tier the confidence the reader should
  place in the ranking based on observation count.
- The data is already in `brain_equity_curve` + `orders` + `fills`
  tables — no new schema, no new collection. Phase 5 is read-only
  analysis on top of existing data.

## Non-Goals (Phase 5)

- **NOT** M4 backtest evidence. The leaderboard explicitly tags rows
  with confidence tier ("early read" / "directional" / "M4-grade")
  based on days-of-data, so no one confuses paper results for edge
  proof.
- **NOT** walk-forward analysis, deflated Sharpe, or out-of-sample
  testing — those belong to Jonathan's `edge-report` workflow (PR #68).
- **NOT** an interactive dashboard. Print to stdout, optional Markdown
  export. No Streamlit page in Phase 5.
- **NOT** automatic brain pruning. The leaderboard shows results; the
  user decides whether to remove a brain from `phase_N_variants()` in
  a follow-up commit.
- **NOT** trade-by-trade attribution or per-event return decomposition.
  Aggregate metrics only.
- **NOT** a new schema column or any change to how brains write equity.

## Architecture

### File layout

| File | Purpose |
|---|---|
| `src/trader/scoring/__init__.py` (new) | Module exports |
| `src/trader/scoring/metrics.py` (new) | Pure functions for Sharpe, max drawdown, hit rate, total return, trade count |
| `src/trader/scoring/leaderboard.py` (new) | `LeaderboardRow` dataclass + `build_leaderboard(store, *, since, until, baseline)` orchestrator |
| `src/trader/scoring/rendering.py` (new) | `render_text_table(rows)` and `render_markdown_table(rows)` formatters |
| `src/trader/cli.py` (modify) | Register `leaderboard` subcommand |
| `tests/financial/test_scoring_metrics.py` (new) | Pure-function metric tests |
| `tests/financial/test_leaderboard_build.py` (new) | Orchestrator tests with synthetic equity curves |
| `tests/financial/test_leaderboard_cli.py` (new) | CLI integration test |

### `LeaderboardRow` dataclass

```python
@dataclass(frozen=True)
class LeaderboardRow:
    brain: str
    days: int                  # number of equity-curve days in window
    total_return: float        # (final / start) - 1
    annualized_return: float   # geometric annualization
    sharpe: float              # mean(daily) / std(daily) * sqrt(252)
    max_drawdown: float        # peak-to-trough max decline, in [-1.0, 0.0]
    hit_rate: float            # fraction of days with positive daily return
    trade_count: int           # rows in `orders` for this brain in window
    vs_buy_and_hold_pp: float  # total_return - buy_and_hold_total_return, in pp
    composite_score: float     # sharpe * (1 - drawdown_penalty)
    confidence_tier: Literal["insufficient", "early_read", "directional", "useful", "m4_grade"]
```

### Confidence tier thresholds

| Days of data | Tier | Display marker |
|---|---|---|
| < 5 | `insufficient` | "—" (not ranked) |
| 5-19 | `early_read` | "EARLY" |
| 20-29 | `directional` | "DIR" |
| 30-99 | `useful` | "OK" |
| >= 100 | `m4_grade` | "★" |

Rows with `confidence_tier == "insufficient"` appear in the output but
are sorted to the bottom and not eligible for the composite_score ranking.

### Composite score

```
composite_score = sharpe * max(0.0, 1.0 - drawdown_penalty)

where drawdown_penalty = min(1.0, |max_drawdown| * 5.0)
```

Rationale: a 20% drawdown halves the Sharpe weight; a 40% drawdown
zeroes it. Penalizes blow-up risk so a brain that gets lucky once
between two collapses doesn't top the board.

### Metric formulas (`scoring/metrics.py`)

All take a list of `(trade_date, equity)` rows already sorted ascending
by date. Pure functions, no I/O, easy to unit-test.

```python
def daily_returns(equity_curve: list[tuple[date, float]]) -> list[float]:
    """Returns the day-over-day percent returns. Length is len(curve) - 1."""

def total_return(equity_curve) -> float:
    """(final / first) - 1. Returns 0.0 if len(curve) < 2."""

def annualized_return(equity_curve, *, trading_days_per_year: int = 252) -> float:
    """Geometric annualization from total return + days span."""

def sharpe_ratio(daily_rets: list[float], *, trading_days_per_year: int = 252) -> float:
    """Annualized Sharpe (risk-free rate = 0). 0.0 if std == 0 or fewer than 2 returns."""

def max_drawdown(equity_curve) -> float:
    """Peak-to-trough max decline. Returns 0.0 (no drawdown) for monotone or single-point curves."""

def hit_rate(daily_rets: list[float]) -> float:
    """Fraction of positive daily returns. 0.5 if fewer than 1 return."""
```

### `build_leaderboard()` orchestrator

```python
def build_leaderboard(
    store: Store,
    *,
    since: date | None = None,
    until: date | None = None,
    baseline_brain: str = "BuyAndHoldBrain",
) -> list[LeaderboardRow]:
    """
    1. Enumerate all distinct brain names with equity-curve rows in window.
    2. Pull `(trade_date, equity)` per brain via `store.get_equity_curve(brain)`.
    3. Filter to since/until.
    4. Compute metrics + confidence_tier.
    5. Compute `vs_buy_and_hold_pp` using baseline_brain's total_return.
       If baseline missing or has insufficient data, leave field at 0.0 and
       note in CLI output (do not crash).
    6. Sort by composite_score DESC, with `insufficient` rows at bottom.
    """
```

### CLI

```
trader-daily leaderboard [--since YYYY-MM-DD] [--until YYYY-MM-DD]
                         [--output FILE] [--baseline BRAIN]
                         [--min-days N]
```

Defaults: no window filter (all available data), baseline `BuyAndHoldBrain`,
text format to stdout, `min_days=5` (hides `insufficient` rows entirely).

Sample stdout (the format Codex should aim for; exact columns may shift):

```
HORSE-RACE LEADERBOARD  —  window: 2026-04-21 → 2026-05-21  (21 days)
baseline: BuyAndHoldBrain  total_return: +4.12%

#  Brain                              Tier  Days  TotRet  Ann.Ret   Sharpe  MaxDD   Hit%  Trades  vs B&H
─────────────────────────────────────────────────────────────────────────────────────────────────────────
1  VIXRegimeAggressive                DIR   21    +6.04%  +84.3%    2.41   -3.1%   62%   4      +1.92pp
2  HybridHaikuAggressive              DIR   21    +5.81%  +79.7%    2.18   -4.0%   57%   6      +1.69pp
3  EarningsToneGPT4oMiniConservative  DIR   21    +4.55%  +60.8%    1.92   -2.8%   59%   3      +0.43pp
…
19 SentimentMomentumConservative      DIR   21    +2.10%  +27.3%    0.61   -5.9%   48%   8      -2.02pp

Tier legend: EARLY (5-19d) / DIR (20-29d) / OK (30-99d) / ★ M4-grade (100+d)
M5-prep horse race. NOT M4 backtest evidence — see brain/16 for the edge gate.
```

Markdown output (`--output report.md`) is the same data with pipe-separated
columns + a Markdown heading.

### Subcommand registration

In `cli.py`:

```python
lb = sub.add_parser("leaderboard", help="Rank brains by risk-adjusted equity performance.")
lb.add_argument("--since", help="Earliest trade_date (YYYY-MM-DD).")
lb.add_argument("--until", help="Latest trade_date (YYYY-MM-DD).")
lb.add_argument("--output", help="Write Markdown to this file instead of stdout.")
lb.add_argument("--baseline", default="BuyAndHoldBrain")
lb.add_argument("--min-days", type=int, default=5)
lb.set_defaults(func=cmd_leaderboard)
```

`cmd_leaderboard()` reads settings, opens `Store(settings.sqlite_path)`,
calls `build_leaderboard()`, renders the right format, prints or writes.

## Acceptance Criteria

1. **`src/trader/scoring/metrics.py`** with pure functions for
   `daily_returns`, `total_return`, `annualized_return`, `sharpe_ratio`,
   `max_drawdown`, `hit_rate` — all spec-compatible signatures.
2. **`src/trader/scoring/leaderboard.py`** with `LeaderboardRow` dataclass
   + `build_leaderboard()` orchestrator + `confidence_tier_for_days()`
   helper.
3. **`src/trader/scoring/rendering.py`** with `render_text_table(rows, *, window, baseline_summary)`
   and `render_markdown_table(rows, *, window, baseline_summary)`.
4. **`leaderboard` subcommand registered** in `cli.py` with `--since`,
   `--until`, `--output`, `--baseline`, `--min-days` flags.
5. **Composite-score formula matches spec** exactly:
   `sharpe * max(0.0, 1.0 - min(1.0, |max_drawdown| * 5.0))`.
6. **Confidence tier thresholds match spec**: <5 → `insufficient`,
   5-19 → `early_read`, 20-29 → `directional`, 30-99 → `useful`,
   >=100 → `m4_grade`.
7. **Sort order**: composite_score DESC for tiers >= `early_read`;
   `insufficient` rows always at bottom.
8. **Baseline brain handling**: if baseline has insufficient data,
   `vs_buy_and_hold_pp` is 0.0 and the header notes the baseline issue;
   command does NOT crash.
9. **Tests** in `tests/financial/`:
    - `test_scoring_metrics.py` — covers each metric function:
      - `total_return`: empty curve → 0.0; single point → 0.0; flat → 0.0; doubling → 1.0.
      - `annualized_return`: 1-year doubling → ~1.0; 1-day +1% → annualized ~12.7x; flat → 0.0.
      - `sharpe_ratio`: zero-variance → 0.0; fewer than 2 returns → 0.0; known input → known output (tolerance 1e-6).
      - `max_drawdown`: monotone up → 0.0; v-shape -20% then recovery → -0.20; single point → 0.0.
      - `hit_rate`: empty → 0.5; all positive → 1.0; all negative → 0.0.
    - `test_leaderboard_build.py` — synthetic store with hand-built
      equity curves for 3 brains; baseline `BuyAndHoldBrain` matters;
      `confidence_tier` correctness across boundary days (4, 5, 19, 20,
      29, 30, 99, 100); sort order; missing baseline doesn't crash;
      `since/until` filter honored; rows with `< min_days` excluded
      when `min_days > insufficient_threshold`.
    - `test_leaderboard_cli.py` — end-to-end via argparse: stdout
      contains expected brain names + tier markers; `--output FILE`
      writes Markdown; `--since/--until` filter applied; baseline
      missing data does not 500.
10. **All existing tests still pass.** No regressions.
11. **Ruff clean.**
12. **Manual smoke** in PR description: assistant runs the command
    against a synthetic SQLite seeded with multi-brain equity curves
    and pastes the rendered table.

## Out of Scope (PR Rejection Triggers)

- Streamlit dashboard
- Walk-forward / deflated Sharpe (Jonathan's edge-report owns that)
- Schema changes to `brain_equity_curve`
- Automatic brain pruning
- Trade-by-trade attribution
- Any change to how brains write equity

## Backward Compat

Phase 5 adds files only — no edits to runner, brains, store schema, or
existing CLI commands. The new subcommand is purely additive. Adding the
scoring module does not change `src/trader/signals/` or `src/trader/runner.py`
at all.

## Rate-Limit Math

The leaderboard command makes zero LLM calls and zero external network
calls. It reads SQLite. Daily/per-cycle cost remains unchanged.

## Safety Boundaries

- No live trading touched.
- No new data writes — the command is read-only.
- The output explicitly tags rows with confidence tiers so paper results
  are not confused with edge proof. The header line includes the framing:
  "M5-prep horse race. NOT M4 backtest evidence."

## Verification

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/financial/ -q
.venv/bin/python -m ruff check src/trader tests/financial
PYTHONPATH=src .venv/bin/python -m trader.cli leaderboard
```

Expected: the command runs against the local SQLite, prints a sorted
leaderboard. Tests pass. Ruff clean.

## What Phase 5 Doesn't Do (And Why That's Fine)

Phase 5 is the *output side* of the horse race. It does not produce M4
edge evidence (Jonathan's `edge-report` workflow in PR #68 covers that).
It does not auto-prune losing brains (that's a manual decision after
reading the board). It does not give statistical significance markers
beyond the day-count tiers (that's also `edge-report`'s job).

Phase 5 succeeds when a user can run `trader-daily leaderboard` and
immediately see "which of the 19 brains is winning, ranked by a metric
that rewards good Sharpe AND penalizes blow-up drawdowns."

After Phase 5, the horse race has:
- **Inputs** (Phases 1-4): 19 brains writing equity rows per cycle
- **Output** (Phase 5): one CLI command to read the verdict

That's the complete M5-prep paper-trading horse race system.
