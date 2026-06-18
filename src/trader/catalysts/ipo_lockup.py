"""Build historical US IPO lock-up-expiry catalyst records.

Final prospectus filing dates are used as a provider-neutral proxy for IPO
dates. The default SEC EDGAR provider is best-effort and returns no records
when its optional dependency or live SEC access is unavailable.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any, Protocol

import pandas as pd

try:
    import structlog
except ModuleNotFoundError:
    structlog = None


class _FallbackLogger:
    """Minimal structured-logging fallback for environments without structlog."""

    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)

    def warning(self, event: str, **context: object) -> None:
        self._logger.warning("%s %s", event, context)


log = structlog.get_logger() if structlog is not None else _FallbackLogger()

_EVENT_COLUMNS = [
    "ticker",
    "cik",
    "company",
    "ipo_date",
    "lockup_expiry_date",
    "lockup_days",
    "source",
    "prospectus_form",
]


@dataclass(frozen=True)
class RawIpoFiling:
    """Provider-neutral final-prospectus filing used to identify an IPO."""

    cik: str
    company: str
    filing_date: date
    form: str
    ticker: str | None = None


@dataclass(frozen=True)
class IpoLockupEvent:
    """Estimated IPO lock-up expiry derived from a final prospectus filing."""

    ticker: str | None
    cik: str
    company: str
    ipo_date: date
    lockup_expiry_date: date
    lockup_days: int
    source: str
    prospectus_form: str


def compute_lockup_expiry(ipo_date: date, lockup_days: int = 180) -> date:
    """Return the estimated lock-up expiry after ``lockup_days`` calendar days.

    The 180-day default is the standard US IPO lock-up convention. Parsing the
    actual per-deal terms from S-1 or 424B prospectus text is a future
    refinement and is intentionally outside this module's scope.
    """

    return ipo_date + timedelta(days=lockup_days)


class IpoFilingProvider(Protocol):
    """Source of provider-neutral final-prospectus IPO filings."""

    def recent_ipo_filings(self, since: date, until: date) -> list[RawIpoFiling]:
        """Return IPO filings whose filing dates fall within the date window."""
        ...


class EdgarIpoFilingProvider:
    """Best-effort IPO filing provider backed by the optional edgartools package."""

    def __init__(self, identity: str | None = None) -> None:
        self._edgar: Any | None = None
        try:
            import edgar

            self._edgar = edgar
            resolved_identity = identity or os.getenv("TRADER_SEC_USER_AGENT")
            if resolved_identity:
                edgar.set_identity(resolved_identity)
        except Exception as exc:
            log.warning("ipo_lockup_edgar_init_failed", error=str(exc))

    def recent_ipo_filings(self, since: date, until: date) -> list[RawIpoFiling]:
        """Fetch 424B4 and 424B1 final prospectuses from SEC EDGAR."""

        if self._edgar is None:
            return []

        try:
            filings: list[RawIpoFiling] = []
            filing_window = f"{since.isoformat()}:{until.isoformat()}"
            for form in ("424B4", "424B1"):
                for filing in self._edgar.get_filings(form=form, filing_date=filing_window):
                    cik = str(filing.cik)
                    filings.append(
                        RawIpoFiling(
                            cik=cik,
                            company=str(filing.company),
                            filing_date=self._filing_date(filing.filing_date),
                            form=str(filing.form),
                            ticker=self._resolve_ticker(cik),
                        )
                    )
            return filings
        except Exception as exc:
            log.warning(
                "ipo_lockup_edgar_fetch_failed",
                since=since.isoformat(),
                until=until.isoformat(),
                error=str(exc),
            )
            return []

    def _resolve_ticker(self, cik: str) -> str | None:
        """Resolve the first ticker exposed by edgartools for a filing CIK."""

        try:
            company = self._edgar.Company(cik)
            tickers = getattr(company, "tickers", None)
            if isinstance(tickers, str):
                return tickers or None
            if tickers:
                return str(tickers[0])
            ticker = getattr(company, "ticker", None)
            return str(ticker) if ticker else None
        except Exception:
            return None

    @staticmethod
    def _filing_date(value: object) -> date:
        """Normalize edgartools filing-date values to ``date``."""

        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value))


def build_ipo_lockup_events(
    since: date,
    until: date,
    *,
    provider: IpoFilingProvider | None = None,
    lockup_days: int = 180,
) -> list[IpoLockupEvent]:
    """Build, deduplicate, and sort estimated IPO lock-up-expiry events."""

    filing_provider = provider or EdgarIpoFilingProvider()
    events: list[IpoLockupEvent] = []
    seen: set[tuple[str, date]] = set()

    for raw in filing_provider.recent_ipo_filings(since, until):
        key = (raw.cik, raw.filing_date)
        if key in seen:
            continue
        seen.add(key)
        events.append(
            IpoLockupEvent(
                ticker=raw.ticker,
                cik=raw.cik,
                company=raw.company,
                ipo_date=raw.filing_date,
                lockup_expiry_date=compute_lockup_expiry(raw.filing_date, lockup_days),
                lockup_days=lockup_days,
                source="edgar",
                prospectus_form=raw.form,
            )
        )

    return sorted(events, key=lambda event: (event.ipo_date, event.ticker or ""))


def events_to_dataframe(events: list[IpoLockupEvent]) -> pd.DataFrame:
    """Convert IPO lock-up events to a DataFrame with stable columns."""

    return pd.DataFrame((asdict(event) for event in events), columns=_EVENT_COLUMNS)
