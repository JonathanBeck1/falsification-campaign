"""HybridBrain v2 prompts: LLM emits discrete enum features, never floats.

Replaces the free-float `hybrid.py` prompt. The output schema lives in
`trader.signals.llm_features.LLMFeatures`; this module formats the prompt
that asks the model to populate it.
"""

from __future__ import annotations

SYSTEM_V2 = """You are a financial news analyst. You receive a packet of recent news
and macro data and return STRUCTURED FEATURES — never a trade decision.

You output discrete labels from a fixed vocabulary. A deterministic policy
downstream maps these labels to a position size. Do not invent labels; do
not output floats or numeric scores.

Output schema (all fields required):
{
  "schema_version": "hybrid-features-v1",
  "sentiment_label": one of ["bullish", "bearish", "neutral", "mixed"],
  "event_tags":      a list (0-5 items) drawn from ["fomc", "earnings", "macro_release", "geopolitical", "none"],
  "severity_bucket": one of ["low", "medium", "high", "breaking"],
  "abstain_reason":  null OR a short string explaining why no confident label could be assigned
}

Bucket guidance:
- "low": routine news, no obvious market mover.
- "medium": notable but contained (single-name earnings beat/miss, sector rotation).
- "high": broad-market-relevant (CPI, NFP, large geopolitical move, regulator action).
- "breaking": market-halting or crisis-level (rate decision surprise, flash crash, war headline).

If the headlines are too sparse or contradictory to label confidently, set
sentiment_label="neutral", severity_bucket="low", event_tags=["none"], and
explain in abstain_reason. Abstention is preferred to a guess.

Output ONLY the JSON, no prose, no code fences.
"""

USER_V2_TEMPLATE = """Snapshot for {ticker} on {trade_date}.

MACRO
- VIX: {vix}
- 10y-2y spread: {curve}
- Fed funds: {fed}
- CPI YoY: {cpi}

RECENT NEWS ({n_news} headlines)
{news_block}

Return the JSON feature object.
"""


def format_user(snapshot) -> str:
    def _fmt(x, sfx: str = "", nd: int = 2) -> str:
        return f"{x:.{nd}f}{sfx}" if isinstance(x, (int, float)) else "n/a"

    news_lines = [f"- [{n.published_at.date()}] {n.headline}" for n in snapshot.news[-10:]]
    news_block = "\n".join(news_lines) if news_lines else "(no recent news)"

    return USER_V2_TEMPLATE.format(
        ticker=snapshot.ticker,
        trade_date=snapshot.trade_date.isoformat(),
        vix=_fmt(snapshot.macro.vix, nd=1),
        curve=_fmt(snapshot.macro.yield_curve_10y_2y),
        fed=_fmt(snapshot.macro.fed_funds),
        cpi=_fmt(snapshot.macro.cpi_yoy, sfx="%", nd=1),
        n_news=len(snapshot.news),
        news_block=news_block,
    )
