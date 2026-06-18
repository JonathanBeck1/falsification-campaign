"""Separate genuine IPOs from the broader 424B prospectus universe.

A 424B4/424B1 final prospectus is filed for *any* registered offering, including
follow-on (secondary) offerings by companies that are already public. For the
lock-up study we need only **first-time IPOs**. The pre-registered definition:

* the company filed an **S-1 or F-1** (initial registration) on or shortly before
  the prospectus date, AND
* it had **no prior periodic report** (10-K/10-Q/20-F/40-F) before that date —
  i.e. it was not already a reporting company, AND
* it is **not a blank-check / SPAC shell** (name heuristic) — SPAC lock-up
  dynamics differ from operating-company IPOs and are out of scope for v1.

``classify_ipo`` and ``is_likely_spac`` are pure and unit-tested. The live
edgartools fetch of a company's filing history is best-effort and lives in
``fetch_form_history`` / ``build_ipo_universe`` (exercised by the runner, not the
unit tests).
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

import structlog

from trader.catalysts.ipo_lockup import (
    EdgarIpoFilingProvider,
    IpoLockupEvent,
    compute_lockup_expiry,
)

log = structlog.get_logger()

_REGISTRATION_PREFIXES = ("S-1", "F-1")
_PRIOR_PUBLIC_PREFIXES = ("10-K", "10-Q", "20-F", "40-F")

# Name patterns that strongly indicate a blank-check / SPAC shell rather than an
# operating-company IPO. Deliberately conservative (high precision).
_SPAC_PATTERNS = (
    r"\bacquisition\b",            # "...Acquisition Corp / Acquisition I Ltd" — strong SPAC tell
    r"\bblank check\b",
    r"\bspac\b",
    r"\bcapital investment corp\b",
)
_SPAC_RE = re.compile("|".join(_SPAC_PATTERNS), re.IGNORECASE)


def is_likely_spac(company_name: str) -> bool:
    """True if the issuer name matches a blank-check / SPAC pattern."""

    return bool(_SPAC_RE.search(company_name or ""))


def _has_prefix(form: str, prefixes: tuple[str, ...]) -> bool:
    f = (form or "").upper().strip()
    return any(f.startswith(p) for p in prefixes)


def classify_ipo(
    form_dates: list[tuple[str, date]],
    ipo_date: date,
    *,
    s1_lookback_days: int = 550,
) -> bool:
    """Decide whether a 424B filer is a genuine first-time IPO.

    ``form_dates`` is the company's filing history as ``(form, filing_date)``
    pairs. Returns True iff an S-1/F-1 registration exists within
    ``s1_lookback_days`` on/before ``ipo_date`` AND no periodic report
    (10-K/10-Q/20-F/40-F) was filed strictly before ``ipo_date``.
    """

    has_registration = any(
        _has_prefix(form, _REGISTRATION_PREFIXES)
        and d <= ipo_date
        and (ipo_date - d).days <= s1_lookback_days
        for form, d in form_dates
    )
    was_public = any(
        _has_prefix(form, _PRIOR_PUBLIC_PREFIXES) and d < ipo_date for form, d in form_dates
    )
    return has_registration and not was_public


def _coerce_date(value: object) -> date:
    if hasattr(value, "date"):
        return value.date()  # type: ignore[no-any-return]
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def fetch_registration_ciks(edgar: Any, since: date, until: date) -> dict[str, date]:
    """Best-effort: earliest S-1/F-1 (incl. amendments) registration date per CIK.

    Used as a fast pre-filter: a 424B4 filer with a recent S-1/F-1 is doing an
    IPO; seasoned issuers register follow-ons on S-3, so they are excluded here
    without a per-company history call.
    """

    reg: dict[str, date] = {}
    window = f"{since.isoformat()}:{until.isoformat()}"
    for form in ("S-1", "S-1/A", "F-1", "F-1/A"):
        try:
            for f in edgar.get_filings(form=form, filing_date=window):
                cik = str(f.cik)
                d = _coerce_date(f.filing_date)
                if cik not in reg or d < reg[cik]:
                    reg[cik] = d
        except Exception as exc:
            log.warning("ipo_universe_registration_fetch_failed", form=form, error=str(exc))
    return reg


def fetch_form_history(edgar: Any, cik: str) -> list[tuple[str, date]]:
    """Best-effort: return a company's ``(form, filing_date)`` history via edgartools."""

    try:
        company = edgar.Company(cik)
        filings = company.get_filings()
        out: list[tuple[str, date]] = []
        for f in filings:
            fd = f.filing_date
            if hasattr(fd, "date"):
                fd = fd.date()
            elif not isinstance(fd, date):
                fd = date.fromisoformat(str(fd))
            out.append((str(f.form), fd))
        return out
    except Exception as exc:
        log.warning("ipo_universe_history_failed", cik=cik, error=str(exc))
        return []


def build_ipo_universe(
    since: date,
    until: date,
    *,
    identity: str | None = None,
    lockup_days: int = 180,
    exclude_spacs: bool = True,
) -> list[IpoLockupEvent]:
    """Live: enumerate 424B prospectuses, keep only genuine first-time IPOs.

    Best-effort and network-bound. Dedups to each company's earliest in-window
    prospectus, classifies via filing history, drops likely SPACs, resolves a
    ticker, and returns sorted ``IpoLockupEvent`` records.
    """

    provider = EdgarIpoFilingProvider(identity=identity)
    edgar = provider._edgar  # reuse the initialised client/identity
    if edgar is None:
        log.warning("ipo_universe_no_edgar")
        return []

    raw = provider.recent_ipo_filings(since, until)

    # Keep each company's earliest in-window prospectus.
    earliest: dict[str, Any] = {}
    for r in raw:
        prev = earliest.get(r.cik)
        if prev is None or r.filing_date < prev.filing_date:
            earliest[r.cik] = r

    # Fast pre-filter: only companies with a recent S-1/F-1 registration are IPO
    # candidates (seasoned follow-ons use S-3). Shrinks the per-company history
    # calls from every 424B filer to just the plausible IPOs.
    reg = fetch_registration_ciks(edgar, since - timedelta(days=550), until)

    events: list[IpoLockupEvent] = []
    n_spac = n_no_recent_s1 = n_notipo = 0
    for cik, r in earliest.items():
        reg_date = reg.get(cik)
        if reg_date is None or not (0 <= (r.filing_date - reg_date).days <= 550):
            n_no_recent_s1 += 1
            continue
        if exclude_spacs and is_likely_spac(r.company):
            n_spac += 1
            continue
        history = fetch_form_history(edgar, cik)
        if not classify_ipo(history, r.filing_date):
            n_notipo += 1
            continue
        ticker = provider._resolve_ticker(cik)
        events.append(
            IpoLockupEvent(
                ticker=ticker,
                cik=cik,
                company=r.company,
                ipo_date=r.filing_date,
                lockup_expiry_date=compute_lockup_expiry(r.filing_date, lockup_days),
                lockup_days=lockup_days,
                source="edgar",
                prospectus_form=r.form,
            )
        )

    log.info(
        "ipo_universe_built",
        raw_filings=len(raw),
        distinct_companies=len(earliest),
        registrations=len(reg),
        excluded_no_recent_s1=n_no_recent_s1,
        excluded_spac=n_spac,
        excluded_not_ipo=n_notipo,
        ipos=len(events),
    )
    return sorted(events, key=lambda e: (e.ipo_date, e.ticker or ""))
