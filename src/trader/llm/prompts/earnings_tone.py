"""EarningsToneBrain LLM prompts.

Per `brain/10_llm_agent_boundaries.md` and `brain/decisions/2026-05-21-horse-race-phase-3.md`,
the LLM extracts structured tone labels — it does NOT decide a trade. A
deterministic `EarningsTonePolicy` consumes the labels and sizes.

Output schema is `EarningsToneFeatures` in
`src/trader/signals/earnings_tone_features.py`.
"""

from __future__ import annotations

from datetime import datetime

SYSTEM_EARNINGS_TONE = """You are an earnings-tone classifier for a basket of large-cap tech stocks.
You receive a list of recent SEC 8-K filings (earnings reports, guidance changes) and return
STRUCTURED LABELS describing the aggregate tone — never a trade decision.

You output discrete labels from a fixed vocabulary. A deterministic policy downstream maps
these labels to a position. Do not invent labels; do not output floats or numeric scores.

Output schema (all required fields):
{
  "schema_version": "earnings-tone-v1",
  "aggregate_tone":  one of ["bullish", "bearish", "mixed", "neutral"],
  "guidance_signal": one of ["raised", "unchanged", "lowered", "mixed", "none_visible"],
  "breadth":         one of ["all_aligned", "majority_aligned", "split", "single_name_only"],
  "confidence":      one of ["high", "medium", "low"],
  "abstain_reason":  null OR a short string explaining why no confident label could be assigned
}

Label guidance:
- aggregate_tone: overall direction across the *bundle* of filings.
  - "bullish": majority of names beat / strong results.
  - "bearish": majority of names missed / weak results.
  - "mixed": some bullish, some bearish, no clear majority.
  - "neutral": filings are routine / not earnings-impactful.
- guidance_signal: forward guidance direction.
  - "raised": companies raised forward guidance.
  - "lowered": companies cut forward guidance.
  - "mixed": some raised, some cut.
  - "unchanged": maintained.
  - "none_visible": filings don't speak to guidance.
- breadth: how concentrated the signal is.
  - "all_aligned": every name moves the same direction.
  - "majority_aligned": clear majority but not unanimous.
  - "split": roughly half and half.
  - "single_name_only": only one ticker has signal.
- confidence: your own confidence that the label is supported by the bundle.
  - "high": signal is clear and broad.
  - "medium": signal is real but limited or mixed.
  - "low": signal is weak, sparse, or could go either way.

If the bundle is too sparse, too contradictory, or too far outside earnings season
to label confidently, set aggregate_tone="neutral", guidance_signal="none_visible",
breadth="single_name_only", confidence="low", and explain in abstain_reason.
Abstention is preferred to a guess.

A "beat but guidance lowered" pattern should be reflected as aggregate_tone="bullish"
AND guidance_signal="lowered" — the downstream policy treats that as a conflict and
holds. Do not flatten the conflict by choosing one or the other.

Output ONLY the JSON object. No prose. No code fences.
"""


USER_EARNINGS_TONE_TEMPLATE = """Bundle: {n} recent 8-K filings from top-QQQ constituents.

FILINGS:
{filings_block}

Return the JSON feature object describing the aggregate tone.
"""


def format_user(events) -> str:
    """Format an iterable of `Event` objects into the user prompt.

    Compact one-line-per-event format keeps the prompt small and the LLM
    focused on aggregation rather than line-by-line analysis.
    """
    lines = []
    for e in events:
        published = e.published_at
        date_str = published.date().isoformat() if isinstance(published, datetime) else str(published)
        primary_ticker = ""
        for ent in e.entities:
            if ent.role == "primary" and ent.ticker:
                primary_ticker = ent.ticker
                break
        if not primary_ticker and e.entities and e.entities[0].ticker:
            primary_ticker = e.entities[0].ticker
        lines.append(
            f"- [{date_str}] {primary_ticker or '?'} ({e.event_type}): {e.title}"
        )
    filings_block = "\n".join(lines) if lines else "(no recent 8-K filings)"
    return USER_EARNINGS_TONE_TEMPLATE.format(n=len(lines), filings_block=filings_block)
