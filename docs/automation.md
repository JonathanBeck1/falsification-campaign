# End-to-End Automation — Operator Guide

Two loops run this project hands-off. Both are user-spawned (terminal `nohup`) so
they inherit Desktop access; both survive the chat session but **not a reboot**
(macOS TCC blocks launchd from reading `~/Desktop`; the workaround is below).

## What's running

| loop | what it does | cadence | log |
|---|---|---|---|
| `scripts/spy_long_run.sh` | grinds the SPY options backfill via ThetaData → exports to lake → refreshes studies | continuous (loop, polls + retries) | `output/spy_long_run.log` |
| `scripts/nightly_loop.sh` | fires `overnight_run.sh` once a night | daily 02:30 local (configurable) | `output/nightly_loop.log` |

`overnight_run.sh` itself runs (continue-on-error):
1. coverage snapshot
2. **SPY backfill** *(skipped automatically when spy_long_run.sh is active — no conflict)*
3. SPY → lake export
4. CEF activist study refresh (live EDGAR)
5. **CEF survival backtest** *(only when `~/.tiingo_key` exists — already set)*
6. **Price strategy lab** (870 ETF variants, deflated-Sharpe + OOS)
7. **QQQ options-signal lab** (48 option-feature variants, same correction)
8. full catalyst test suite
9. coverage snapshot

Survivor dashboards auto-refresh the moment a phase writes its JSON.

## Operating

```bash
# Status
pgrep -fl 'spy_long_run|nightly_loop'         # what's alive
tail -f output/nightly_loop.log               # nightly fires
tail -f output/spy_long_run.log               # SPY backfill grind
ls -t output/overnight_*.log | head -1        # latest batch log

# Start (after reboot, or to relaunch)
cd /ABSOLUTE/PATH/TO/trader-catalyst
caffeinate -s nohup scripts/spy_long_run.sh   >/dev/null 2>&1 &
caffeinate -s nohup scripts/nightly_loop.sh   >/dev/null 2>&1 &

# Start nightly_loop with an immediate first pass (skip the first sleep)
RUN_NOW=1 caffeinate -s nohup scripts/nightly_loop.sh >/dev/null 2>&1 &

# Change the schedule (e.g. fire at 23:15 instead of 02:30)
NIGHTLY_HOUR=23 NIGHTLY_MIN=15 caffeinate -s nohup scripts/nightly_loop.sh >/dev/null 2>&1 &

# Stop
pkill -f spy_long_run.sh && rm -f output/spy_long_run.lock
pkill -f nightly_loop.sh && rm -f output/nightly_loop.lock

# Manual one-shot run (uses current state, skips backfill if long-run alive)
caffeinate -s scripts/overnight_run.sh
```

## Prerequisites (all in place)

- Java 21+ at `/opt/homebrew/opt/openjdk` (installed via `brew install openjdk`).
- ThetaData Terminal jar at `~/ThetaTerminal/ThetaTerminal.jar` + creds at
  `~/ThetaTerminal/creds.txt` (chmod 600). Auto-launched by
  `scripts/start_thetadata.sh` (idempotent — checks port 25510 first).
- External drive **Express 1M2** mounted (185 GB SQLite store + parquet lake).
- `~/.tiingo_key` (chmod 600) — auto-loaded by `overnight_run.sh`.
- Python 3.12 venv at `.venv/` with all deps (`trading`, `dashboard`, `dev`).

## Reboot behavior (honest)

**The loops do not survive a reboot.** macOS TCC blocks `launchd` from reading
scripts under `~/Desktop` (the failure mode we hit during setup). After a reboot:

1. `scripts/start_thetadata.sh` — relaunches the ThetaData Terminal (idempotent).
2. Re-run the two `caffeinate -s nohup …` lines above from a terminal.

To make it truly reboot-proof, you have two options:

- **Move the repo off `~/Desktop`** (e.g. to `~/dev/trader-catalyst`), then
  `scripts/install_launchd.sh install` registers the long-run as a launchd
  agent (the plist is already in `scripts/com.trader.spy-long-run.plist`).
- **Grant Full Disk Access to `/bin/bash`** in System Settings → Privacy &
  Security → Full Disk Access. Then launchd can read Desktop and the same
  installer works.

## Dashboard (Streamlit)

```bash
.venv/bin/streamlit run src/trader/dashboard/catalyst_app.py
# http://localhost:8501
```

Views auto-update from on-disk artifacts the loops produce — refresh the page
after a loop pass to see new survivor data.
