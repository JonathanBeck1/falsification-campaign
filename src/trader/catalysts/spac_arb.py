"""Measure the SPAC trust-arbitrage edge for a small trader.

The trade: a SPAC holds ~$10/share of T-bills in trust. Pre-deal shares are
redeemable for trust + accrued interest at the deal/liquidation deadline, so a
share bought *below* trust value implies a near-riskless yield to redemption,
plus free optionality if a deal pops the price. This module measures the
currently-available "discount to trust" across a live SPAC sample.

Design notes (match the rest of ``trader.catalysts``):
- ``from __future__ import annotations``, structlog, frozen dataclasses.
- Every network path is best-effort: it logs a warning and returns an empty /
  ``None`` result rather than raising, so a study loop can skip a name and
  continue.

Three data sources, all already proven to work in this environment:
- EDGAR full-text search (``efts.sec.gov``) to list SPAC IPO prospectuses
  (424B4 with "blank check" language) and parse ticker + CIK from
  ``display_names``.
- yfinance for live prices of SPACs that have NOT yet been purged (delisted /
  liquidated SPACs return ``YFPricesMissingError`` and are simply absent).
- edgartools XBRL facts (``us-gaap:AssetsHeldInTrust`` /
  ``TemporaryEquitySharesOutstanding``) to anchor trust-per-share against the
  latest 10-Q instead of assuming a flat number.

CRITICAL SURVIVORSHIP CAVEAT (see ``research/spac_arb_report.md``): yfinance
purges delisted tickers, so this module can only observe SPACs that are STILL
trading. Already-redeemed / liquidated SPACs — the ones that actually paid out
the trust arb — are invisible here. The live distribution therefore measures
*currently available* discount, not *realized* return.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date
from statistics import mean, median
from typing import Any

import pandas as pd
import structlog

log = structlog.get_logger()

EFTS_URL = "https://efts.sec.gov/LATEST/search-index"

# Trust-value assumption when no 10-Q figure is available. A SPAC IPOs at
# $10.00/share into a T-bill trust; at ~5% short rates, ~1-2 years of accrued
# interest lifts trust per share to roughly $10.5-$11.0. We default to $10.60,
# the low-middle of that band and consistent with the 10-Q figures actually
# observed for clean pre-deal names (FACT $10.59, OACC $10.60, CCIX $10.79,
# MACI $10.81, SBXD $10.76). Justified empirically in the report.
DEFAULT_TRUST_PER_SHARE = 10.60

# A SPAC that has not yet announced/closed a deal trades in a tight band around
# trust. Outside this band the ticker is almost always a post-deal operating
# company (price >> trust) or a busted/penny de-SPAC (price << trust) that kept
# the original ticker — neither is the pre-deal arb. We use the band to isolate
# genuine pre-deal SPACs from the contaminated yfinance ticker set.
PREDEAL_LOW = 9.0
PREDEAL_HIGH = 13.5

_SAMPLE_COLUMNS = ["ticker", "cik", "company", "ipo_date", "source"]
_QUOTE_COLUMNS = [
    "ticker",
    "cik",
    "company",
    "price",
    "trust_per_share",
    "trust_source",
    "discount_pct",
    "annualized_yield_pct",
    "is_predeal_band",
]


@dataclass(frozen=True)
class SpacListing:
    """A SPAC identified from an EDGAR 424B4 ("blank check") prospectus."""

    ticker: str | None
    cik: str
    company: str
    ipo_date: date
    source: str = "edgar_fts"


@dataclass(frozen=True)
class SpacQuote:
    """A live discount-to-trust measurement for one SPAC."""

    ticker: str
    cik: str | None
    company: str | None
    price: float
    trust_per_share: float
    trust_source: str
    discount_pct: float
    annualized_yield_pct: float
    is_predeal_band: bool


# --------------------------------------------------------------------------- #
# Pure logic (network-free, unit-tested)
# --------------------------------------------------------------------------- #


def parse_display_name(display_name: str) -> tuple[str, str | None, str | None]:
    """Parse an EDGAR ``display_names`` entry into ``(company, ticker, cik)``.

    Format: ``"Acme Acquisition Corp.  (ACME, ACMER, ACMEU)  (CIK 0001234567)"``.
    The first parenthesised group that is not the CIK holds the ticker symbols;
    the first symbol is the common share class (others are R=rights, U=unit,
    W=warrant). Returns ``ticker=None`` when no symbol is published yet.
    """

    cik_match = re.search(r"\(CIK\s+(\d+)\)", display_name)
    cik = cik_match.group(1) if cik_match else None

    ticker: str | None = None
    for group in re.findall(r"\(([^()]+)\)", display_name):
        if group.strip().startswith("CIK"):
            continue
        first = group.split(",")[0].strip()
        if re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,6}", first):
            ticker = first
            break

    company = display_name.split("  (")[0].strip()
    return company, ticker, cik


def discount_pct(trust_per_share: float, price: float) -> float:
    """Return the discount to trust as a fraction of price.

    Positive means price is *below* trust (the favourable arb entry); negative
    means a premium to trust (deal optimism priced in). Defined relative to
    price because that is the capital actually deployed.
    """

    if price <= 0:
        raise ValueError("price must be positive")
    return (trust_per_share - price) / price


def annualized_yield(
    trust_per_share: float, price: float, months_to_redemption: float
) -> float:
    """Annualize the redemption payoff ``trust/price`` over the holding period.

    ``(trust / price) ** (12 / months) - 1``. A share bought at ``price`` that
    redeems at ``trust_per_share`` after ``months_to_redemption`` earns this
    compound annual rate (ignoring accrued interest between now and redemption,
    which makes the estimate conservative). Raises on non-positive inputs.
    """

    if price <= 0 or trust_per_share <= 0:
        raise ValueError("price and trust_per_share must be positive")
    if months_to_redemption <= 0:
        raise ValueError("months_to_redemption must be positive")
    return (trust_per_share / price) ** (12.0 / months_to_redemption) - 1.0


def is_predeal_band(price: float, low: float = PREDEAL_LOW, high: float = PREDEAL_HIGH) -> bool:
    """True if ``price`` is in the plausible pre-deal SPAC band around trust.

    Used to strip post-deal operating companies and busted penny de-SPACs that
    reused the SPAC ticker from the live sample.
    """

    return low <= price <= high


def summarize_discounts(quotes: list[SpacQuote]) -> dict[str, float]:
    """Summary stats of the discount/yield distribution over pre-deal quotes.

    Only quotes flagged ``is_predeal_band`` contribute; the rest are de-SPAC
    contamination. Returns an empty dict when there is nothing to summarize.
    """

    predeal = [q for q in quotes if q.is_predeal_band]
    if not predeal:
        return {}

    discounts = [q.discount_pct for q in predeal]
    yields = [q.annualized_yield_pct for q in predeal]
    n_at_discount = sum(1 for d in discounts if d > 0)
    return {
        "n_predeal": float(len(predeal)),
        "n_at_discount": float(n_at_discount),
        "n_at_premium": float(len(predeal) - n_at_discount),
        "discount_pct_median": median(discounts),
        "discount_pct_mean": mean(discounts),
        "discount_pct_min": min(discounts),
        "discount_pct_max": max(discounts),
        "annualized_yield_median": median(yields),
        "annualized_yield_mean": mean(yields),
    }


# --------------------------------------------------------------------------- #
# Best-effort network providers
# --------------------------------------------------------------------------- #


def fetch_spac_listings(
    start: date,
    end: date,
    *,
    query: str = '"blank check"',
    form: str = "424B4",
    max_results: int = 400,
    user_agent: str | None = None,
) -> list[SpacListing]:
    """List SPAC IPO prospectuses from EDGAR full-text search in ``[start, end]``.

    Best-effort: any network/parse failure logs a warning and returns whatever
    was gathered so far (possibly empty). Deduplicated by CIK.
    """

    try:
        import os

        import httpx
    except Exception as exc:  # pragma: no cover - import guard
        log.warning("spac_listings_import_failed", error=str(exc))
        return []

    agent = user_agent or os.getenv("TRADER_SEC_USER_AGENT") or "catalyst-research"
    headers = {"User-Agent": agent}
    seen: dict[str, SpacListing] = {}
    offset = 0
    try:
        while offset < max_results:
            params = {
                "q": query,
                "forms": form,
                "startdt": start.isoformat(),
                "enddt": end.isoformat(),
                "from": offset,
            }
            resp = httpx.get(EFTS_URL, params=params, headers=headers, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
            hits = payload.get("hits", {}).get("hits", [])
            if not hits:
                break
            for hit in hits:
                source = hit.get("_source", {})
                names = source.get("display_names") or []
                if not names:
                    continue
                company, ticker, cik = parse_display_name(names[0])
                if not cik or cik in seen:
                    continue
                seen[cik] = SpacListing(
                    ticker=ticker,
                    cik=cik,
                    company=company,
                    ipo_date=_parse_date(source.get("file_date")),
                )
            total = payload.get("hits", {}).get("total", {}).get("value", 0)
            offset += len(hits)
            if offset >= total:
                break
    except Exception as exc:
        log.warning(
            "spac_listings_fetch_failed",
            start=start.isoformat(),
            end=end.isoformat(),
            gathered=len(seen),
            error=str(exc),
        )

    return sorted(seen.values(), key=lambda s: (s.ipo_date, s.ticker or ""))


def fetch_live_price(ticker: str) -> float | None:
    """Return the latest close for ``ticker`` via yfinance, or ``None``.

    Delisted / liquidated SPACs return no data (``YFPricesMissingError``) and
    yield ``None`` — the survivorship hole documented in the report.
    """

    try:
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import yfinance as yf

            df = yf.download(
                ticker, period="10d", auto_adjust=True, progress=False, threads=False
            )
    except Exception as exc:
        log.warning("spac_price_fetch_failed", ticker=ticker, error=str(exc))
        return None

    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df = df.droplevel(axis=1, level=1)
    if "Close" not in df.columns:
        return None
    close = df["Close"].dropna()
    if close.empty:
        return None
    return float(close.iloc[-1])


def fetch_trust_per_share(cik: str, *, identity: str | None = None) -> float | None:
    """Trust value per redeemable share from the latest 10-Q XBRL, or ``None``.

    Reads ``us-gaap:AssetsHeldInTrust(Noncurrent)`` divided by the redeemable
    share count (``TemporaryEquitySharesOutstanding`` /
    ``CommonStockSharesSubjectToPossibleRedemption``). Best-effort: returns
    ``None`` on any failure, or when the implied per-share value is outside a
    sane $1-$25 range (guards against partial-redemption SPACs whose XBRL mixes
    pre/post-redemption figures — see the SPKL caveat in the report).
    """

    try:
        import os

        import edgar
    except Exception as exc:  # pragma: no cover - import guard
        log.warning("spac_trust_import_failed", error=str(exc))
        return None

    resolved = identity or os.getenv("TRADER_SEC_USER_AGENT")
    try:
        if resolved:
            edgar.set_identity(resolved)
        filing = edgar.Company(cik).get_filings(form="10-Q").latest(1)
        if filing is None:
            return None
        facts = filing.xbrl().facts.to_dataframe()
    except Exception as exc:
        log.warning("spac_trust_fetch_failed", cik=cik, error=str(exc))
        return None

    trust = _max_fact(facts, ("us-gaap:AssetsHeldInTrustNoncurrent", "us-gaap:AssetsHeldInTrust"))
    shares = _max_fact(
        facts,
        (
            "us-gaap:TemporaryEquitySharesOutstanding",
            "us-gaap:CommonStockSharesSubjectToPossibleRedemption",
        ),
    )
    if not trust or not shares or shares < 1_000:
        return None
    per_share = trust / shares
    if not 1.0 <= per_share <= 25.0:
        log.warning("spac_trust_per_share_out_of_range", cik=cik, value=per_share)
        return None
    return per_share


def build_quote(
    listing: SpacListing,
    *,
    use_filed_trust: bool = False,
    months_to_redemption: float = 9.0,
    default_trust: float = DEFAULT_TRUST_PER_SHARE,
    identity: str | None = None,
) -> SpacQuote | None:
    """Assemble a live discount-to-trust quote for one SPAC listing.

    Returns ``None`` if there is no ticker or no live price (delisted). When
    ``use_filed_trust`` is set, anchors trust-per-share to the latest 10-Q and
    falls back to ``default_trust`` if extraction fails.
    """

    if not listing.ticker:
        return None
    price = fetch_live_price(listing.ticker)
    if price is None or price <= 0:
        return None

    trust = default_trust
    trust_source = "assumed"
    if use_filed_trust:
        filed = fetch_trust_per_share(listing.cik, identity=identity)
        if filed is not None:
            trust, trust_source = filed, "10q_xbrl"

    return SpacQuote(
        ticker=listing.ticker,
        cik=listing.cik,
        company=listing.company,
        price=price,
        trust_per_share=trust,
        trust_source=trust_source,
        discount_pct=discount_pct(trust, price),
        annualized_yield_pct=annualized_yield(trust, price, months_to_redemption),
        is_predeal_band=is_predeal_band(price),
    )


def listings_to_dataframe(listings: list[SpacListing]) -> pd.DataFrame:
    """Convert SPAC listings to a DataFrame with stable columns."""

    return pd.DataFrame((asdict(item) for item in listings), columns=_SAMPLE_COLUMNS)


def quotes_to_dataframe(quotes: list[SpacQuote]) -> pd.DataFrame:
    """Convert SPAC quotes to a DataFrame with stable columns."""

    return pd.DataFrame((asdict(q) for q in quotes), columns=_QUOTE_COLUMNS)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _parse_date(value: object) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except Exception:
        return date(1970, 1, 1)


def _max_fact(facts: Any, concepts: tuple[str, ...]) -> float | None:
    """Return the largest positive numeric value among ``concepts`` in ``facts``.

    The latest 10-Q reports several period columns; the largest positive value
    is the current-period figure for trust assets and redeemable share counts.
    """

    try:
        rows = facts[facts["concept"].isin(concepts)]
    except Exception:
        return None
    values: list[float] = []
    for raw in rows.get("value", []):
        try:
            num = float(raw)
        except (TypeError, ValueError):
            continue
        if num > 0:
            values.append(num)
    return max(values) if values else None
