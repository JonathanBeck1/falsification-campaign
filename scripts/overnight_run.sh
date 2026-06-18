#!/usr/bin/env bash
# Overnight batch runner. Does the genuinely-useful automatable work while you sleep.
#
# Launch (keeps the Mac awake while plugged in):
#     caffeinate -s scripts/overnight_run.sh
#
# Prerequisites for the SPY backfill task (the big one):
#   1. External drive "Express 1M2" mounted.
#   2. ThetaData Terminal running (REST on 127.0.0.1:25510).
# If either is missing, the backfill is skipped and the rest still runs.
#
# Everything is logged, and one task failing never kills the batch.

set -u
MAIN="/ABSOLUTE/PATH/TO/trades"
WT="/ABSOLUTE/PATH/TO/trader-catalyst"
export TRADER_SEC_USER_AGENT="catalyst-research you@example.com"
[ -f "$HOME/.tiingo_key" ] && export TIINGO_API_KEY="$(cat "$HOME/.tiingo_key")"  # auto-enables the survival backtest
LOG="$WT/output/overnight_$(date +%Y%m%d_%H%M%S).log"
mkdir -p "$WT/output"
exec > >(tee -a "$LOG") 2>&1

echo "================ OVERNIGHT RUN $(date) ================"

run() { echo; echo "----- $1 -----"; shift; "$@" || echo "[task exited $?]"; }

# 0. Coverage snapshot (before)
run "coverage (before)" "$WT/.venv/bin/python" "$WT/scripts/refresh_coverage.py"

# 1. SPY options backfill — resumable; skips done ledger days. THE high-value task.
# Skip if a separate spy_long_run.sh is already handling it (avoid ThetaData conflict).
LONG_RUN_ACTIVE=0
pgrep -f spy_long_run.sh >/dev/null 2>&1 && LONG_RUN_ACTIVE=1
THETA_OK=0
if [ -d "/Volumes/Express 1M2" ] && curl -s -o /dev/null --max-time 3 http://127.0.0.1:25510/v2/system/mdds/status; then
  THETA_OK=1
fi
if [ "$LONG_RUN_ACTIVE" = "1" ]; then
  echo; echo "----- SPY backfill -----"; echo "[skipped] spy_long_run.sh is already handling SPY"
elif [ "$THETA_OK" = "1" ]; then
  run "SPY backfill 2020->2026 (resumable)" \
      bash -c "cd '$MAIN' && .venv/bin/python -m trader.cli options-backfill-thetadata-quotes \
               --ticker SPY --start 2020-01-02 --end 2026-06-06"
  run "SPY export to lake" \
      bash -c "cd '$MAIN' && .venv/bin/python -m trader.cli options-export-parquet-lake \
               --ticker SPY --out $HOME/trader-lake-fast"
else
  echo; echo "----- SPY backfill -----"
  echo "[skipped] need external drive mounted AND ThetaData Terminal on 127.0.0.1:25510"
fi

# 2. CEF activist study refresh (live EDGAR + yfinance) — picks up any NEW Saba 13Ds.
run "CEF activist study refresh" \
    bash -c "cd '$WT' && .venv/bin/python -u scripts/run_cef_study.py"

# 2b. CEF survival backtest — only when a Tiingo key is present (the real number).
if [ -n "${TIINGO_API_KEY:-}" ]; then
  run "CEF survival backtest (Tiingo)" \
      bash -c "cd '$WT' && .venv/bin/python -u scripts/run_cef_survival.py"
else
  echo; echo "----- CEF survival backtest -----"; echo "[skipped] set TIINGO_API_KEY for the real run"
fi

# 2c. Strategy-mining lab — re-mine hundreds of variants (deflated-Sharpe + OOS),
#     refreshing the dashboard's Strategy Lab view.
run "strategy-mining lab (price)" \
    bash -c "cd '$WT' && .venv/bin/python -u scripts/run_strategy_lab.py"

# 2d. QQQ option-signal lab (uses cached features; differentiated-data edge hunt).
run "options-signal lab (QQQ)" \
    bash -c "cd '$WT' && .venv/bin/python -u scripts/run_options_lab.py"

# 2e. QQQ options v2 (richer features: GEX/skew/flow/spread/depth/term-curv).
run "options-signal lab v2 (QQQ)" \
    bash -c "cd '$WT' && .venv/bin/python -u scripts/run_options_lab_v2.py"

# 2f. Cross-sectional / pairs / sector-rotation / lead-lag / dispersion.
run "cross-sectional lab" \
    bash -c "cd '$WT' && .venv/bin/python -u scripts/run_cross_sectional_lab.py"

# 2g. Multi-asset / regime signals (bonds-eq, gold-eq, VIX, credit, etc.).
run "multi-asset lab" \
    bash -c "cd '$WT' && .venv/bin/python -u scripts/run_multi_asset_lab.py"

# 2h. Small-cap / niche-ETF universe (capacity-constrained universe).
run "small-universe lab" \
    bash -c "cd '$WT' && .venv/bin/python -u scripts/run_small_universe_lab.py"

# 2i. Pre-2010 OOS extension (SPY/DIA/EWJ 1993-2009 IS / 2010-2025 OOS).
run "pre-2010 lab" \
    bash -c "cd '$WT' && .venv/bin/python -u scripts/run_pre2010_lab.py"

# 3. Verify the full catalyst test suite still green.
run "catalyst tests" \
    bash -c "cd '$WT' && .venv/bin/python -m pytest \
             tests/financial/test_cef_study.py tests/financial/test_cef_resolution.py \
             tests/financial/test_cef_survival_backtest.py tests/financial/test_tiingo.py \
             tests/financial/test_lockup_study.py tests/financial/test_ipo_universe.py \
             tests/financial/test_ipo_lockup.py tests/financial/test_spac_arb.py \
             tests/financial/test_insider_clusters.py tests/financial/test_index_rebalance.py -q"

# 4. Coverage snapshot (after — shows backfill progress)
run "coverage (after)" "$WT/.venv/bin/python" "$WT/scripts/refresh_coverage.py"

echo; echo "================ DONE $(date) ================"
echo "Log: $LOG"
echo "Open the dashboard's Data Coverage view to see SPY progress."
