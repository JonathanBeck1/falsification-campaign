"""Normalize Yahoo Finance news items into Event records.

Yahoo's per-ticker news endpoint loosely associates items with the queried
ticker(s). We attach those tickers as `mentioned` entities with lower
confidence than Finnhub (Yahoo's tagging is noisier).

For broad-market ETFs (SPY/QQQ), articles are usually macro/index commentary,
so we tag asset_scope accordingly.

Classifier note: keyword matching uses word-boundary regexes plus
co-occurrence requirements rather than naive substring search. The earlier
substring version mislabeled headlines like "Fed-up customers complain about
FedEx" and "tax rate cuts to boost growth" as `fed_commentary`. The new
classifier requires `Fed` (as a token) to co-occur with monetary-policy
context, or `FOMC`/`Powell` (which are unambiguous on their own), or an
interest-rate action phrase.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from trader.normalization.finnhub import classify_event_type, classify_urgency
from trader.normalization.models import Entity, Event, EvidenceSnippet, stable_event_id
from trader.storage.snapshot import NewsItem

_INDEX_TICKERS = {"SPY", "QQQ", "DIA", "IWM", "^GSPC", "^IXIC", "^DJI", "^RUT", "^VIX"}


# Compile once at module load — these run on every Yahoo headline.
_FOMC_OR_POWELL = re.compile(r"\b(?:fomc|powell)\b", re.IGNORECASE)
_BARE_FED = re.compile(r"\bfed\b", re.IGNORECASE)
_MONETARY_CONTEXT = re.compile(
    r"\b(?:rate|rates|policy|meeting|chair|hike|hikes|cut|cuts|"
    r"basis[-\s]points?|dovish|hawkish|easing|tightening|"
    r"interest[-\s]rates?|reserve|monetary|tapering|qe|quantitative)\b",
    re.IGNORECASE,
)
_INTEREST_RATE_ACTION = re.compile(
    r"\binterest[-\s]rates?\b[^.]*\b(?:cut|cuts|hike|hikes|raise|raised|"
    r"lower|lowered|decision|change[d]?|policy)\b",
    re.IGNORECASE,
)

_MACRO_TERMS = re.compile(
    r"\b(?:inflation|cpi|ppi|jobs[-\s]report|nonfarm|payrolls?|"
    r"unemployment|gdp|recession|pmi|retail[-\s]sales|consumer[-\s]price)\b",
    re.IGNORECASE,
)

_EARNINGS_TERMS = re.compile(
    r"\b(?:earnings|results|revenue|profits?|q[1-4]\s+\d{4}|quarterly|eps)\b",
    re.IGNORECASE,
)

_GUIDANCE_RAISE = re.compile(
    r"\b(?:raises?\s+(?:guidance|outlook|forecast)|boosts?\s+forecast|"
    r"guidance\s+raise[d]?|lifted\s+(?:guidance|outlook))\b",
    re.IGNORECASE,
)
_GUIDANCE_LOWER = re.compile(
    r"\b(?:lowers?\s+(?:guidance|outlook|forecast)|cuts?\s+(?:guidance|outlook|forecast)|"
    r"slashes?\s+forecast|guidance\s+cut)\b",
    re.IGNORECASE,
)

# Analyst actions need analyst context to avoid matching "iOS upgrade" etc.
_ANALYST_CONTEXT = re.compile(
    r"\b(?:analyst|rating|price[-\s]target|broker|firm|wall[-\s]street)\b",
    re.IGNORECASE,
)
_UPGRADE_VERB = re.compile(r"\b(?:upgrade[ds]?|raised|hiked)\b", re.IGNORECASE)
_DOWNGRADE_VERB = re.compile(r"\b(?:downgrade[ds]?|lowered|slashed)\b", re.IGNORECASE)
_PRICE_TARGET_RAISED = re.compile(r"\bprice[-\s]target[s]?\s+raised\b", re.IGNORECASE)
_PRICE_TARGET_CUT = re.compile(r"\bprice[-\s]target[s]?\s+(?:cut|lowered|slashed)\b", re.IGNORECASE)

# Social-velocity events: derivative/social-flow specific phrasing only.
# Plain "options" used to false-match on "optional", "options-rich pension".
_SOCIAL_VELOCITY = re.compile(
    r"\b(?:short[-\s]squeeze|meme[-\s]stock|gamma[-\s]squeeze|"
    r"unusual[-\s]options|options[-\s]flow|wallstreetbets|reddit[-\s]rally|"
    r"halted|trading[-\s]halt)\b",
    re.IGNORECASE,
)


def _is_fed_commentary(text: str) -> bool:
    """FOMC/Powell mentioned anywhere → fed. Bare 'Fed' needs monetary context."""
    if _FOMC_OR_POWELL.search(text):
        return True
    if _BARE_FED.search(text) and _MONETARY_CONTEXT.search(text):
        return True
    return bool(_INTEREST_RATE_ACTION.search(text))


def classify_yahoo_event_type(headline: str, summary: str = "") -> str:
    """Classify broad Yahoo market headlines with conservative keyword rules.

    Order matters — earlier rules win. Fed commentary is checked first because
    monetary news drives the broader market more than single-name earnings.
    """
    text = f"{headline} {summary}"

    if _is_fed_commentary(text):
        return "fed_commentary"
    if _MACRO_TERMS.search(text):
        return "macro_surprise"
    if _GUIDANCE_RAISE.search(text):
        return "guidance_raise"
    if _GUIDANCE_LOWER.search(text):
        return "guidance_lower"
    if _EARNINGS_TERMS.search(text):
        return "earnings_surprise"
    if _PRICE_TARGET_RAISED.search(text) or (
        _UPGRADE_VERB.search(text) and _ANALYST_CONTEXT.search(text)
    ):
        return "analyst_upgrade"
    if _PRICE_TARGET_CUT.search(text) or (
        _DOWNGRADE_VERB.search(text) and _ANALYST_CONTEXT.search(text)
    ):
        return "analyst_downgrade"
    if _SOCIAL_VELOCITY.search(text):
        return "unusual_social_velocity"
    return classify_event_type(headline, summary)


def classify_yahoo_urgency(headline: str, summary: str = "") -> str:
    text = f"{headline} {summary}"
    if _is_fed_commentary(text):
        return "high"
    if _SOCIAL_VELOCITY.search(text):
        return "high"
    return classify_urgency(headline)


def yahoo_news_to_events(
    items: list[NewsItem],
    *,
    queried_tickers: list[str],
    observed_at: datetime | None = None,
) -> list[Event]:
    """Convert Yahoo NewsItems queried under `queried_tickers` into Event records.

    `queried_tickers` is the list passed to fetch_yahoo_news (e.g. ["QQQ","SPY"]).
    We don't know which specific queried ticker each item came from after the
    merge/dedup, so we attach all as `mentioned` candidates with moderate
    confidence.
    """
    now = observed_at or datetime.now(UTC)
    normalized_tickers = sorted({t.upper() for t in queried_tickers})
    is_index_query = any(t in _INDEX_TICKERS for t in normalized_tickers)
    asset_scope = ["index", "macro"] if is_index_query else ["single_name"]
    index_exposure = [t for t in normalized_tickers if t in _INDEX_TICKERS]

    out: list[Event] = []
    for item in items:
        event_type = classify_yahoo_event_type(item.headline, item.summary)
        urgency = classify_yahoo_urgency(item.headline, item.summary)
        classified_at = now
        out.append(
            Event(
                # Event identity is intentionally independent of `queried_tickers`.
                # The same story queried with ["QQQ","SPY"] vs ["QQQ","SPY","IWM"]
                # is one event in the world — it must dedup to one row regardless
                # of how the caller asked for it. Ticker attribution lives in
                # `entities` / `index_exposure`, not in the id.
                event_id=stable_event_id("yahoo_finance", item.headline, item.published_at),
                source="yahoo_finance",
                source_url="",
                title=item.headline,
                summary=item.summary,
                published_at=item.published_at,
                observed_at=now,
                ingested_at=now,
                classified_at=classified_at,
                entities=[Entity(name=t, ticker=t, confidence=0.55, role="mentioned") for t in normalized_tickers],
                asset_scope=asset_scope,
                index_exposure=index_exposure,
                event_type=event_type,
                sentiment="neutral",
                sentiment_score=0.0,
                urgency=urgency,
                novelty_score=0.4,  # Yahoo recycles wire stories
                source_credibility=0.6,
                evidence=[
                    EvidenceSnippet(
                        text=(item.summary or item.headline)[:300],
                        location="yfinance",
                    )
                ],
                model_outputs=[],
                raw_artifact_path="",
            )
        )
    return out
