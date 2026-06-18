# Decision: PEAD lab killed — classic look-ahead bug

Date: 2026-06-09
Status: killed.

## What appeared
PEAD study reported PASS: N=1095 earnings events, positive-minus-negative
car_0_p21 = +3.74%, Welch t = +6.11, stable across OOS halves.

## What was wrong
Cohort split: `prev_day_reaction = close[t0] / close[t0-1] - 1` — the announcement-day
return. Cohort assigned by sign of this return.
Measurement: `car_0_p21` STARTS at t0, so the announcement-day return is INCLUDED
in the CAR. The cohort split and the first day of the CAR are the SAME return.
This is mechanical: "stocks that went up on day 0 went up on day 0" tautology.

## The fix-check (5 tickers, 115 events, small sample)
- Buggy diff (car_0_p21 inclusive): +0.10% (already small)
- Fixed diff (car_+1_p21, excluding cohort-defining day): **−3.70%**

The true post-announcement drift on this sample is NEGATIVE — the buggy result
was entirely the day-0 contamination. The "+3.74% in 1095 events" was a
double-count, not real PEAD.

## Action
- Removed `output/catalysts/pead_study.json` so dashboard doesn't display it.
- Counted as kill. A proper PEAD study would shift the CAR window to [+1,+22]
  excluding the announcement day; deferred until needed.

## Lesson
Classic event-study pitfall: NEVER include the cohort-defining day in the
measurement window. Same defect class as the cross-sectional SPY/IVV
"survivors" (different mechanism, same outcome: machine flagged "real",
human verification killed it).
