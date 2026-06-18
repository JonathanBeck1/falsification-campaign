# Pre-Registration: <STRATEGY NAME> (Txx)

> Status: pre-registered design, written **before** collecting or inspecting
> results. The hypothesis, sample, windows, split, gate, and kill criteria are
> fixed here so a favorable specification cannot be selected after the fact.
>
> This is the standard campaign template (see `brain/34_master_test_registry.md`
> and the universal gate in `brain/30_campaign_findings.md`). Fill every field;
> delete the `<...>` placeholders. Keep it tight.

## 1. Hypothesis (one sentence, directional, falsifiable)

<e.g. "Cohort X earns a positive after-cost abnormal return vs a matched control
over window W.">

## 2. Mechanism — why would this be inefficient?

<Name the economic/behavioral reason the edge could exist AND persist: who is
the forced/uninformed counterparty, what friction stops it being arbed away.
"It's a published anomaly" is not a mechanism — state WHY it might survive.>

**Honest prior:** <small / null / marginal? cite the decay literature if any.>

## 3. Data + provenance

- **Instrument(s) / universe (fixed):** <list or rule; no post-hoc selection.>
- **Source:** <yfinance / EDGAR / exchange API / owned lake — name it.>
- **Construction & staleness:** <adjusted? derived? as-of lag? any survivorship?>
- **Event/date list:** <how derived; hardcoded vs fetched; is it knowable ex-ante?>
- **Sample span:** IS <start..end> · OOS <start..end>.

## 4. Cohort & control definition

- **Cohort (treated):** <exact rule defining membership.>
- **Control / baseline:** <matched (ticker, year) / pooled universe / non-event
  days — the discipline that absorbs drift the cohort would otherwise inherit.>
- **Abnormal return / signal:** <stock ret − benchmark ret, beta=1, etc.>
- **t0:** <first trading day on/after the event; state the convention.>

## 5. Measurement window + LOOK-AHEAD statement

- **Windows (event time, inclusive):** <e.g. car_0_p21; mark the PRIMARY.>
- **Look-ahead audit:** <State exactly what information defines the cohort and
  prove the measurement window starts strictly AFTER it. If the event date is
  legitimately known ex-ante (e.g. a published calendar), say so explicitly —
  ex-ante knowability is a feature, not leakage.>

## 6. Friction model

- **Round-trip cost:** <bps; e.g. SPY ~2 bps, single-name ~5–10 bps; cite.>
- **Application:** subtract once per round trip from gross expectancy; after-cost
  expectancy is the ONLY ranked metric.

## 7. Pre-registered gate (ALL must hold — from brain/30)

- [ ] **N ≥ 30** usable events.
- [ ] **After-cost expectancy** positive with **|t| ≥ 2.0** on the PRIMARY window.
- [ ] **OOS sign stability** — IS and OOS halves the same sign, both N ≥ 10
      (test honestly for decay).
- [ ] **Pooled baseline** — cohort minus universe baseline; up/down symmetry check.
- [ ] **Matched-control / placebo** — composition-matched or pseudo-event placebo
      shows ~0; claim requires placebo null AND net |t| ≥ 2.
- [ ] **Too-good tripwire** — Sharpe > 3, win rate > 85%, or median far from mean
      auto-triggers a placebo run + top-5 contributor inspection before any write-up.
- [ ] **Data provenance** — source, construction, staleness documented (§3).

No alternative window may replace the PRIMARY if the primary gate fails.

## 8. Pre-registered KILL criteria

Kill the idea if ANY holds:

- After-cost PRIMARY |t| < 2, OR after-cost expectancy ≤ 0.
- N < 30 usable events under the fixed rules.
- OOS sign flip (effect decayed / regime-dependent).
- Placebo/matched-control absorbs the effect (net |t| < 2 or perm p ≥ 0.05).
- Fewer than 5 events drive the result (remove top contributors → effect vanishes).

## 9. Limitations

<Known data walls, coarse controls, untested sub-claims. State what a kill
does NOT prove.>
