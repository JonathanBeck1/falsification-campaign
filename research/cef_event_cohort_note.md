# CEF event cohort (Phase 5 / T21 free groundwork)

Multi-filer EDGAR event detection (`scripts/build_cef_event_cohort.py`, generalized
`cef_events.py`): activist 13D entries from Saba/Karpus/Bulldog/City of London/Ancora/
Relative Value + termination forms (N-8F, 25/25-NSE, N-14, liquidation proxies),
2015-2026.

- **Raw output** `output/cef/cef_event_cohort.parquet` = 11,055 events across 8,193 CIKs.
  This is an UNFILTERED SUPERSET — the termination detection (delisting/merger/dereg)
  matches ALL investment companies that filed those forms, not just CEFs. Not usable
  as-is.
- **Filtered cohort** `output/cef/cef_event_cohort_filtered.parquet` = **270 events
  across 183 funds** = the raw cohort ∩ the Tiingo CEF universe (648 price tickers).
  Breakdown: activist_entry 126, merger 68, delisting 68, liquidation 5, dereg 3.
  This is the usable T21 cohort and matches brain/32's order-of-magnitude estimate.

Caveat: ticker-based intersection misses dead funds whose tickers don't resolve
(the CIK-join gap from brain/32); a CIK-based intersection against the resolved-CIK
subset (326) would differ. The activist side (126) is the cleaner half.

NEXT (needs Tiingo NAV, a purchase): matched-control discount-decile study on this
cohort per brain/32 — NOT done here (free groundwork only).
