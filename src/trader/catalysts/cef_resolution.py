"""Label Saba CEF activist campaigns by OUTCOME and find 13D-time predictors.

For each Saba Capital SC 13D campaign on a closed-end fund (CEF), we ask: did the
fund **resolve** (liquidate / merge / open-end / large tender-at-NAV — the events
that close the discount and pay the activist) or did it **fizzle** (the fund keeps
trading at a discount, Saba accumulates/agitates with no terminal event)?

Resolution is read from the subject fund's EDGAR filing history *after* the 13D
date plus a delisting flag. The classifier is **pure and unit-tested**; the live
EDGAR / yfinance fetches are best-effort (network failures log and return empty).

Signal taxonomy (what each form tells us), strongest first:

* ``N-8F``      — application to deregister under the '40 Act. Filed when a fund
                  has **completed** a liquidation or merger and ceases to exist.
                  This is the gold-standard "it's over, it resolved" signal.
* ``25`` / ``25-NSE`` — exchange delisting notice. A fund delists when it
                  liquidates or merges. Strong resolution signal.
* ``N-14 8C`` / ``425`` / ``DEFM14A`` — merger registration / proxy. The fund is
                  being merged into another fund (often an open-end or a larger
                  sister fund). Resolution = merger.
* ``DEF 14A``/``DEFA14A`` with a shareholder-approved liquidation or open-ending
                  proposal — captured only indirectly (we cannot read proxy text
                  here), so a DEF 14A alone is NOT treated as resolution.
* ``SC TO-I``   — issuer self-tender. Saba's wins are often a tender for a *large*
                  fraction (e.g. 30-100%) of shares at/near NAV. But routine
                  managed-distribution tenders also use SC TO-I, so a bare SC TO-I
                  is a WEAK signal — only counted as resolution when paired with a
                  delisting or deregistration.
* ``N-23C-2``   — notice of intent to redeem securities. For perpetual muni funds
                  this fires **semiannually** to redeem term-preferred shares and
                  is pure NOISE; we ignore it entirely.

Delisting flag: a target with **no yfinance price data** has almost certainly been
delisted (liquidation/merger), which is itself a resolution signal even when we
cannot pin the exact form.

The classifier deliberately errs toward "resolved only on hard evidence" so the
resolution RATE is a lower bound, not an oversell.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()

# --- Form taxonomy -----------------------------------------------------------

# Hard "the fund ceased to exist" forms — almost always a completed resolution.
DEREGISTRATION_FORMS = frozenset({"N-8F"})
DELISTING_FORMS = frozenset({"25", "25-NSE"})
# Merger registration / merger proxy.
MERGER_FORMS = frozenset({"N-14 8C", "N-14 8C/A", "425", "DEFM14A", "PREM14C", "DEFM14C"})
# Self-tender — weak on its own (see module docstring).
TENDER_FORMS = frozenset({"SC TO-I", "SC TO-I/A", "SC TO-T"})
# Forms we explicitly treat as noise for resolution purposes.
NOISE_FORMS = frozenset({"N-23C-2", "N-23C3"})

# Outcome labels.
OUT_DEREGISTERED = "deregistered"  # N-8F: liquidation/merger completed
OUT_DELISTED = "delisted"  # 25/25-NSE or no price data
OUT_MERGER = "merger"  # N-14 8C / 425 / DEFM14A
OUT_TENDER = "tender"  # large self-tender (corroborated)
OUT_ONGOING = "ongoing"  # no resolution evidence (fizzle-or-pending)

RESOLVED_LABELS = frozenset({OUT_DEREGISTERED, OUT_DELISTED, OUT_MERGER, OUT_TENDER})


@dataclass(frozen=True)
class ResolutionLabel:
    """Outcome of one campaign, derived purely from forms + a delisting flag."""

    outcome: str
    resolved: bool
    resolution_date: date | None
    # The (form, date) that triggered the label, for auditing.
    trigger_form: str | None
    days_to_resolution: int | None


@dataclass(frozen=True)
class CampaignFeatures:
    """13D-time-observable features used to predict resolution.

    All of these are knowable on the SC 13D filing date (the name is known; the
    amendment count is a *post-hoc* escalation proxy and is flagged as such — it
    is NOT observable at t0, but is reported as a within-sample correlate).
    """

    ticker: str
    cik: str
    name: str
    filing_date: date
    sponsor: str
    is_municipal: bool
    is_term_fund: bool
    is_equity_or_alt: bool
    amendment_count: int  # post-hoc: # of SC 13D/A after the initial 13D


@dataclass(frozen=True)
class CampaignOutcome:
    """A campaign joined with its features and resolution label."""

    features: CampaignFeatures
    label: ResolutionLabel


# --- Pure classifier ---------------------------------------------------------


def classify_resolution(
    form_history: list[tuple[str, date]],
    filing_date: date,
    *,
    has_price_data: bool,
) -> ResolutionLabel:
    """Map a subject's filing history (+ a price-data flag) to an outcome.

    PURE: no I/O. ``form_history`` is the subject fund's full ``(form, date)``
    history; only filings strictly AFTER ``filing_date`` are considered (the 13D
    is the event; pre-existing forms cannot be a *response* to Saba). The earliest
    qualifying signal in priority order sets the label and resolution date.

    Priority: deregistration (N-8F) > delisting (25) > merger > corroborated
    tender > no-price-data delisting > ongoing.
    """

    after = sorted(
        (
            (f.upper().strip(), d)
            for f, d in form_history
            if d > filing_date and f
        ),
        key=lambda fd: fd[1],
    )

    def _first(forms: frozenset[str]) -> tuple[str, date] | None:
        norm = {x.upper() for x in forms}
        for f, d in after:
            if f in norm:
                return f, d
        return None

    dereg = _first(DEREGISTRATION_FORMS)
    delist = _first(DELISTING_FORMS)
    merger = _first(MERGER_FORMS)
    tender = _first(TENDER_FORMS)

    # 1. Deregistration — the fund has ceased to exist. Strongest.
    if dereg is not None:
        return _mk(OUT_DEREGISTERED, dereg, filing_date)
    # 2. Exchange delisting notice.
    if delist is not None:
        return _mk(OUT_DELISTED, delist, filing_date)
    # 3. Merger registration / proxy.
    if merger is not None:
        return _mk(OUT_MERGER, merger, filing_date)
    # 4. Self-tender — only counts when corroborated by absence of price data
    #    (i.e. the tender was terminal / the fund subsequently went away). A bare
    #    SC TO-I with the fund still trading is a managed-distribution tender, not
    #    a resolution.
    if tender is not None and not has_price_data:
        return _mk(OUT_TENDER, tender, filing_date)
    # 5. No price data at all but no hard form found ⇒ delisted-unknown. Still a
    #    resolution signal (the fund left the market) but with no date/trigger.
    if not has_price_data:
        return ResolutionLabel(
            outcome=OUT_DELISTED,
            resolved=True,
            resolution_date=None,
            trigger_form="(no price data)",
            days_to_resolution=None,
        )
    # 6. No evidence of resolution.
    return ResolutionLabel(
        outcome=OUT_ONGOING,
        resolved=False,
        resolution_date=None,
        trigger_form=None,
        days_to_resolution=None,
    )


def _mk(outcome: str, trigger: tuple[str, date], filing_date: date) -> ResolutionLabel:
    form, d = trigger
    return ResolutionLabel(
        outcome=outcome,
        resolved=True,
        resolution_date=d,
        trigger_form=form,
        days_to_resolution=(d - filing_date).days,
    )


# --- Feature extraction (pure) ----------------------------------------------

# Sponsor families, matched against the fund name (longest/most-specific first).
_SPONSOR_PATTERNS: tuple[tuple[str, str], ...] = (
    ("BlackRock", "blackrock"),
    ("Nuveen", "nuveen"),
    ("Invesco", "invesco"),
    ("Eaton Vance", "eaton vance"),
    ("BNY Mellon", "bny mellon"),
    ("BNY Mellon", "dreyfus"),
    ("abrdn", "abrdn"),
    ("Tortoise", "tortoise"),
    ("ClearBridge", "clearbridge"),
    ("MFS", "mfs "),
    ("DWS", "dws "),
    ("Pioneer", "pioneer"),
    ("Neuberger Berman", "neuberger"),
    ("Clough", "clough"),
    ("Adams", "adams"),
    ("AllianceBernstein", "alliancebernstein"),
    ("Cushing", "cushing"),
    ("Calamos", "calamos"),
    ("Gabelli", "gabelli"),
    ("Lazard", "lazard"),
    ("Voya", "voya"),
    ("Virtus", "virtus"),
    ("First Trust", "first trust"),
    ("Macquarie", "macquarie"),
    ("Federated Hermes", "federated"),
    ("Destra", "destra"),
    ("Principal", "principal real estate"),
    ("Delaware", "delaware investments"),
    ("Templeton", "templeton"),
    ("Morgan Stanley", "morgan stanley"),
    ("New Germany", "new germany"),
    ("Miller/Howard", "miller/howard"),
    ("Ecofin", "ecofin"),
    ("Western Asset", "western asset"),
    ("New America", "new america"),
    ("MainStay", "mainstay"),
)

_MUNI_KEYWORDS = ("municipal", "muni", "tax-free", "tax free")
_TERM_KEYWORDS = ("term trust", "term fund", " term ")


def classify_sponsor(name: str) -> str:
    n = (name or "").lower()
    for label, pat in _SPONSOR_PATTERNS:
        if pat in n:
            return label
    return "Other"


def is_municipal_fund(name: str) -> bool:
    n = (name or "").lower()
    return any(k in n for k in _MUNI_KEYWORDS)


def is_term_fund(name: str) -> bool:
    n = (name or "").lower()
    return any(k in n for k in _TERM_KEYWORDS)


def extract_features(
    ticker: str,
    cik: str,
    name: str,
    filing_date: date,
    *,
    amendment_count: int = 0,
) -> CampaignFeatures:
    """Pure: derive name-based features. ``amendment_count`` is supplied by the
    caller (counted from EDGAR) — it is a post-hoc escalation proxy, NOT t0-known.
    """

    muni = is_municipal_fund(name)
    term = is_term_fund(name)
    return CampaignFeatures(
        ticker=ticker,
        cik=cik,
        name=name,
        filing_date=filing_date,
        sponsor=classify_sponsor(name),
        is_municipal=muni,
        is_term_fund=term,
        is_equity_or_alt=not muni,
        amendment_count=amendment_count,
    )


# --- Live collection (best-effort, network-bound) ---------------------------


def load_campaigns(path: str | Path) -> list[tuple[str, str, str, date]]:
    """Read the campaign CSV -> ``(ticker, cik, name, filing_date)`` rows."""

    rows: list[tuple[str, str, str, date]] = []
    p = Path(path)
    try:
        with p.open(newline="") as fh:
            for r in csv.DictReader(fh):
                rows.append(
                    (
                        r["ticker"].strip(),
                        str(r["cik"]).strip(),
                        r["name"].strip(),
                        date.fromisoformat(r["filing_date"].strip()),
                    )
                )
    except Exception as exc:
        log.warning("cef_resolution_load_failed", path=str(p), error=str(exc))
    return rows


def count_amendments(form_history: list[tuple[str, date]], filing_date: date) -> int:
    """Count SC 13D/A amendments filed after the initial 13D (escalation proxy)."""

    n = 0
    for f, d in form_history:
        fu = (f or "").upper().strip()
        if d > filing_date and ("13D/A" in fu or fu == "SCHEDULE 13D/A"):
            n += 1
    return n


def has_yfinance_data(ticker: str) -> bool:
    """Best-effort: True if yfinance still serves price data (⇒ not delisted)."""

    try:
        import warnings

        import yfinance  # type: ignore

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            hist = yfinance.Ticker(ticker).history(period="3mo")
        return hist is not None and len(hist) > 0
    except Exception as exc:
        log.warning("cef_resolution_yf_failed", ticker=ticker, error=str(exc))
        # Treat an *error* as "unknown" -> caller may default to True so we do not
        # over-count resolutions on a transient failure. We return True (alive).
        return True


def build_outcome(
    edgar: Any,
    ticker: str,
    cik: str,
    name: str,
    filing_date: date,
    *,
    check_price: bool = True,
) -> CampaignOutcome:
    """Live: fetch one subject's history, label it, and attach features."""

    from trader.catalysts.ipo_universe import fetch_form_history

    history = fetch_form_history(edgar, cik)
    has_price = has_yfinance_data(ticker) if check_price else True
    label = classify_resolution(history, filing_date, has_price_data=has_price)
    feats = extract_features(
        ticker,
        cik,
        name,
        filing_date,
        amendment_count=count_amendments(history, filing_date),
    )
    log.info(
        "cef_resolution_labeled",
        ticker=ticker,
        outcome=label.outcome,
        resolved=label.resolved,
        trigger=label.trigger_form,
    )
    return CampaignOutcome(features=feats, label=label)


def resolution_rate(outcomes: list[CampaignOutcome]) -> float:
    """Fraction of campaigns labeled resolved."""

    if not outcomes:
        return 0.0
    return sum(1 for o in outcomes if o.label.resolved) / len(outcomes)
