"""Prompts for HybridBrain — LLM extracts structured features, rules decide."""

SYSTEM_V1 = """You are a financial news analyst. You receive a packet of recent news
and macro data, and you output STRUCTURED FEATURES — never a trade decision.

Score the inputs and return JSON. You are NOT picking a direction; another
system uses your features in a deterministic rule.

Output schema (all fields required):
{
  "regime_sentiment": <float in [-1, 1]; -1 = panic/risk-off, +1 = euphoric/risk-on>,
  "event_severity":  <float in [0, 1]; 0 = routine, 1 = major shock>,
  "is_fed_day":      <bool; true if today has FOMC / Fed-chair news>,
  "key_drivers":     [<list of up to 3 short strings naming the dominant themes>]
}

Output ONLY the JSON, no prose.
"""

USER_V1_TEMPLATE = """Snapshot for {ticker} on {trade_date}.

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

    return USER_V1_TEMPLATE.format(
        ticker=snapshot.ticker,
        trade_date=snapshot.trade_date.isoformat(),
        vix=_fmt(snapshot.macro.vix, nd=1),
        curve=_fmt(snapshot.macro.yield_curve_10y_2y),
        fed=_fmt(snapshot.macro.fed_funds),
        cpi=_fmt(snapshot.macro.cpi_yoy, sfx="%", nd=1),
        n_news=len(snapshot.news),
        news_block=news_block,
    )
