# Overnight Build Plan

A prioritized, honest roadmap of long-running tasks to grind through overnight.
Honesty first: we proved there's **no large systematic edge** here, so the durable
value of overnight work is **data infrastructure and tooling**, plus *cheap*
long-shot research — not a hunt for a miracle. Tasks are tiered by real value.

## The super-long run (active)

`scripts/spy_long_run.sh` is the persistent grinder: it **waits** for ThetaData,
then loops the SPY backfill to 100%, **exports SPY to the lake**, and refreshes
the studies — resumable, single-instance, self-healing. It is launched detached:

```bash
cd /ABSOLUTE/PATH/TO/trader-catalyst
caffeinate -s nohup scripts/spy_long_run.sh >/dev/null 2>&1 &
```

**The only thing you must do: open the ThetaData Terminal app.** The run is
already active and waiting; the moment ThetaData is up it starts backfilling
automatically. Watch it: dashboard **🗄️ Data Coverage**, or
`tail -f output/spy_long_run.log`.

- **Stop it:** `pkill -f spy_long_run.sh && rm -f output/spy_long_run.lock`
- **Persistence:** survives this chat session (detached) but **not a reboot** —
  macOS blocks launchd from running scripts under `~/Desktop` (TCC). For
  reboot-persistence, grant Full Disk Access to `/bin/bash` OR move the repo off
  the Desktop, then `scripts/install_launchd.sh install`. Otherwise just re-run
  the `caffeinate -s nohup …` line after a reboot.

## One-shot nightly batch (alternative)

```bash
caffeinate -s scripts/overnight_run.sh        # runs the batch once and exits
```

Logs to `output/overnight_<timestamp>.log`; never lets one task kill the rest.

**Prerequisites for the SPY backfill (the big task):**
1. External drive **"Express 1M2"** mounted (the 185 GB store + lake live there).
2. **ThetaData Terminal running** (REST on `127.0.0.1:25510`).
If either is missing, the backfill is skipped and the rest still runs.

---

## Current data status (2026-06-09)

| ticker | coverage | rows | span | in lake? |
|---|---|---|---|---|
| **QQQ** | **100%** (1,613 days) | 578M | 2020-01-02 → 2026-06-03 | yes |
| **SPY** | **12%** (194 sampled days) | 109M | 2020-01-02 → 2024-06-03 | no |

SPY is the obvious gap. Completing it is multi-night (≈1,400 missing days at
~450k rows/day) and **resumable** (the ledger tracks done days), so each night's
run makes durable progress.

---

## Tier 1 — high value, automatable (in the runner)

1. **Complete the SPY options backfill** → match QQQ (2020–2026).
   `options-backfill-thetadata-quotes --ticker SPY --start 2020-01-02 --end 2026-06-06`
   Resumable; several nights to finish. *This is the single most valuable task.*
2. **Export SPY to the parquet lake** once backfilled (DuckDB read path the
   studies use). *Add to runner after SPY crosses ~80%.*
3. **Coverage tracking** — `scripts/refresh_coverage.py` writes the dashboard JSON
   before & after each run so you can watch SPY climb. (In runner.)
4. **CEF activist study refresh** — re-run on live EDGAR to catch any new Saba
   13D campaigns and fresh prices. (In runner.)
5. **Test suite verification** — keep the catalyst engine green. (In runner.)

## Tier 2 — medium value, to build

6. **SPY out-of-sample re-runs.** Once SPY is backfilled, re-run the (already
   falsified) condor / premium studies on SPY as an independent OOS check.
   Honest EV: we expect this to *confirm* "no edge," not reverse it — but it's the
   pending cross-ticker validation and it's cheap once the data exists.
7. **New catalyst buckets** (no ThetaData; EDGAR + yfinance), each pre-registered
   then run overnight like the lock-up/CEF studies:
   - **Form-4 insider-cluster buying** — the insider signal with the most
     literature support. Honest prior: probably fails like the rest.
   - **Index add/delete (S&P/Nasdaq reconstitution)** — heavily studied; expect
     decay.

## Tier 3 — tooling & the one live lead

8. **CEF survival backtest** — the real validation of the only surviving lead.
   Blocked on delisted-price data: add a free **Tiingo** key (retains delisted
   EOD) or parse terminal values from N-8F / final N-CSR / N-14 filings, then run
   a survival/cohort backtest of a muni + fast-sponsor tilted basket.
9. **Dashboard enhancements** — live CEF discount watchlist for the tilt;
   per-study charts; a lake-coverage heatmap by date.

---

## What the runner does tonight (concretely)

`scripts/overnight_run.sh`, in order, continue-on-error:
0. coverage snapshot (before)
1. **SPY backfill** (if ThetaData + drive present) — resumable
2. **CEF activist study refresh** (live)
3. **catalyst test suite**
4. coverage snapshot (after)

To make it a nightly habit, wrap it in a `launchd`/cron job or the repo's
scheduled-task tooling — but start with one manual `caffeinate -s` run to confirm
the ThetaData path is healthy.
