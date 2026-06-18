"""Build a catalog of large single-day moves and their likely catalysts.

Pipeline (one event at a time, resumable):
  1. detect_events: identify (ticker, date) pairs with |daily_return| >= threshold
  2. fetch_8k_for_event: EDGAR 8-K filings on/near event_date (edgartools)
  3. fetch_alpaca_news_for_event: Benzinga-powered headlines t-2 to t+2
  4. classify_with_claude: Sonnet 4.6 reads context → structured JSON catalog row
  5. append to parquet (atomic — no half-writes)

Honest framing on what this can and cannot answer:
  * What it CAN do: produce a structured catalog of which categories of catalyst
    surround large moves (8-K item types, news themes), with article timing
    relative to the move.
  * What it CAN'T do: prove causation. Many articles are post-hoc rationalizations.
    The CATALOG is the deliverable. Predictive testing (Phase 3) is a separate gate
    via the existing falsification machine.
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import pandas as pd
import structlog

log = structlog.get_logger()

# Configuration ---------------------------------------------------------------
DEFAULT_TICKERS = [
    "NVDA", "AAPL", "MSFT", "AMZN", "META", "GOOGL", "TSLA",
    "AVGO", "BRK-B", "JPM", "QQQ", "SPY",
]
DEFAULT_THRESHOLD = 0.04  # |daily_return| >= 4%
DEFAULT_START = "2020-01-01"
DEFAULT_END = "2026-06-08"


# --- 1. Event detection -----------------------------------------------------
@dataclass(frozen=True)
class LargeMoveEvent:
    ticker: str
    date: date
    daily_return: float
    abs_return: float
    spy_return: float | None
    spy_excess: float | None  # ticker - spy = idiosyncratic
    direction: str            # 'up' or 'down'


def detect_events(
    tickers: list[str] = DEFAULT_TICKERS,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    start: str = DEFAULT_START,
    end: str = DEFAULT_END,
) -> list[LargeMoveEvent]:
    """Identify all |return| >= threshold days per ticker, with market context."""

    import yfinance as yf

    try:
        spy_df = yf.download("SPY", start=start, end=end, auto_adjust=True, progress=False, threads=False)
        spy_close = spy_df["Close"].squeeze().dropna() if not spy_df.empty else None
        if spy_close is not None and isinstance(spy_close, pd.DataFrame):
            spy_close = spy_close.iloc[:, 0]
        spy_ret = spy_close.pct_change() if spy_close is not None else None
    except Exception as exc:
        log.warning("catalog_spy_fetch_failed", error=str(exc))
        spy_ret = None

    events: list[LargeMoveEvent] = []
    for ticker in tickers:
        try:
            df = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False, threads=False)
        except Exception as exc:
            log.warning("catalog_ticker_fetch_failed", ticker=ticker, error=str(exc))
            continue
        if df is None or df.empty:
            continue
        close = df["Close"].squeeze().dropna()
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        ret = close.pct_change().dropna()
        big = ret[ret.abs() >= threshold]
        for ts, r in big.items():
            d = ts.date() if hasattr(ts, "date") else ts
            spy_r = None
            spy_x = None
            if spy_ret is not None and ts in spy_ret.index:
                spy_r = float(spy_ret.loc[ts])
                spy_x = float(r) - spy_r
            events.append(LargeMoveEvent(
                ticker=ticker,
                date=d,
                daily_return=float(r),
                abs_return=float(abs(r)),
                spy_return=spy_r,
                spy_excess=spy_x,
                direction="up" if r > 0 else "down",
            ))
    events.sort(key=lambda e: (e.date, e.ticker))
    return events


# --- 2. 8-K fetcher (edgartools) ---------------------------------------------
def fetch_8k_for_event(ticker: str, event_date: date, *, window_days: int = 2) -> list[dict]:
    """Return any 8-K filings for `ticker` within ±window_days of event_date."""

    try:
        import edgar
        identity = os.getenv("TRADER_SEC_USER_AGENT")
        if identity:
            edgar.set_identity(identity)
        # Find company by ticker
        try:
            company = edgar.Company(ticker.replace("-", "."))
        except Exception:
            return []
        since = (event_date - timedelta(days=window_days)).isoformat()
        until = (event_date + timedelta(days=window_days)).isoformat()
        filings = company.get_filings(form="8-K")
        out: list[dict] = []
        for f in filings:
            fd = f.filing_date
            if hasattr(fd, "date"):
                fd = fd.date()
            elif not isinstance(fd, date):
                try:
                    fd = date.fromisoformat(str(fd))
                except Exception:
                    continue
            if not (since <= fd.isoformat() <= until):
                continue
            try:
                text = f.text()[:6000]  # truncate
            except Exception:
                text = ""
            # Extract item numbers via regex
            import re
            items = sorted(set(re.findall(r"Item\s+(\d\.\d{1,2})", text, re.IGNORECASE)))
            out.append({
                "filing_date": fd.isoformat(),
                "form": str(getattr(f, "form", "8-K")),
                "items": items,
                "text_excerpt": text[:2000],
            })
        return out
    except Exception as exc:
        log.warning("catalog_8k_failed", ticker=ticker, date=event_date.isoformat(), error=str(exc))
        return []


# --- 3. Alpaca News (Benzinga) for historical news --------------------------
def fetch_alpaca_news_for_event(
    ticker: str,
    event_date: date,
    *,
    window_days: int = 2,
    limit: int = 25,
) -> list[dict]:
    """Return Benzinga-powered news from Alpaca for the event window."""

    key = os.getenv("ALPACA_PAPER_KEY_ID") or os.getenv("ALPACA_API_KEY")
    secret = os.getenv("ALPACA_PAPER_SECRET_KEY") or os.getenv("ALPACA_SECRET_KEY")
    if not key or not secret:
        return []
    since = (event_date - timedelta(days=window_days)).isoformat() + "T00:00:00Z"
    until = (event_date + timedelta(days=window_days)).isoformat() + "T23:59:59Z"
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    params = {"symbols": ticker, "start": since, "end": until, "limit": str(limit), "sort": "asc"}
    try:
        resp = httpx.get("https://data.alpaca.markets/v1beta1/news", headers=headers,
                         params=params, timeout=20.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("catalog_alpaca_news_failed", ticker=ticker, error=str(exc))
        return []
    out = []
    for n in data.get("news", []):
        out.append({
            "published_at": n.get("created_at") or n.get("updated_at"),
            "headline": (n.get("headline") or "")[:200],
            "summary": (n.get("summary") or "")[:1000],
            "source": n.get("source"),
            "url": n.get("url"),
        })
    return out


# --- 4. Classifier (Claude Sonnet 4.6) --------------------------------------
CATALYST_CATEGORIES = [
    "earnings_results",      # quarterly results / guidance
    "guidance_update",       # mid-quarter
    "merger_acquisition",    # M&A
    "exec_change",           # CEO/CFO/board
    "regulatory_action",     # SEC/DOJ/FTC/FDA
    "macro_fed",             # FOMC, Fed speakers
    "macro_data",            # CPI, NFP, GDP, etc.
    "geopolitical",          # war, tariffs, sanctions
    "product_news",          # launch, recall, partnership
    "analyst_action",        # major upgrade/downgrade
    "market_wide_selloff",   # SPY also moved >1.5% same direction (no single-name cause)
    "rotation_flow",         # sector rotation, index rebal, large fund flow
    "idiosyncratic_unknown", # no clear public cause
    "other",
]

_CLASSIFIER_PROMPT = """You are classifying the most likely catalyst for a single-day large stock move.

EVENT:
- Ticker: {ticker}
- Date: {date}
- Daily return: {ret:+.2%}  (direction: {direction})
- SPY same day: {spy}
- Excess vs SPY: {excess}

8-K FILINGS (from the company on/near this date, if any):
{filings_block}

NEWS HEADLINES (around the event):
{news_block}

TASK: Classify the most likely catalyst. Output JSON only, no prose. Schema:
{{
  "category": one of {categories},
  "subcategory": brief free-text (e.g. "earnings_beat", "FOMC_hawkish_surprise", "tariff_announcement", "FDA_approval"),
  "confidence": one of ["high", "medium", "low"],
  "article_relative_timing": one of ["before_move", "during_move_day", "after_move", "unclear", "no_article"],
  "brief_explanation": one short sentence,
  "is_market_wide": boolean (true if SPY also moved materially same direction),
  "evidence_snippet": one short quote from filings/news that supports the classification, or null
}}

Rules:
- If 8-K item 2.02 is present, category is almost certainly earnings_results.
- If SPY moved more than 1.5% same direction with no single-name catalyst evident, prefer market_wide_selloff.
- If neither filing nor news is informative, use idiosyncratic_unknown with low confidence.
- Be skeptical of post-hoc rationalizations: an article AFTER the move that just says "stock fell on concerns" without specifics is weak evidence.
"""


def _classifier_messages(
    event: LargeMoveEvent,
    filings: list[dict],
    news: list[dict],
) -> list[dict]:
    spy_str = (
        f"{event.spy_return*100:+.2f}% (excess {event.spy_excess*100:+.2f}%)"
        if event.spy_return is not None else "n/a"
    )
    excess_str = f"{event.spy_excess*100:+.2f}%" if event.spy_excess is not None else "n/a"

    if filings:
        filings_block = "\n".join(
            f"- {f['filing_date']} {f['form']} items={f['items']}: {f['text_excerpt'][:500].strip()}"
            for f in filings[:5]
        )
    else:
        filings_block = "(none)"

    if news:
        news_block = "\n".join(
            f"- [{n['published_at']}] [{n.get('source','?')}] {n['headline']}: {n['summary'][:300]}"
            for n in news[:10]
        )
    else:
        news_block = "(none — Alpaca News may not cover this date or symbol)"

    prompt = _CLASSIFIER_PROMPT.format(
        ticker=event.ticker,
        date=event.date.isoformat(),
        ret=event.daily_return,
        direction=event.direction,
        spy=spy_str,
        excess=excess_str,
        filings_block=filings_block,
        news_block=news_block,
        categories=CATALYST_CATEGORIES,
    )
    return [{"role": "user", "content": prompt}]


@dataclass(frozen=True)
class ClassificationResult:
    category: str
    subcategory: str
    confidence: str
    article_relative_timing: str
    brief_explanation: str
    is_market_wide: bool
    evidence_snippet: str | None
    model: str
    input_tokens: int       # not tracked under Codex / ChatGPT Plus auth
    output_tokens: int
    cost_usd: float         # 0.0 under Codex sub (counts against ChatGPT quota, not $)


def classify_with_codex(
    event: LargeMoveEvent,
    filings: list[dict],
    news: list[dict],
    *,
    model: str = "gpt-5.5",
    timeout_s: int = 120,
) -> ClassificationResult | None:
    """Classify via Codex CLI (uses ChatGPT Plus auth — no API key, no $ cost).

    Codex is invoked with --sandbox read-only (no file edits) and
    --output-last-message so we get only the final agent message (no session
    headers). The prompt asks for a JSON object; we parse it.
    """

    import subprocess
    import tempfile

    messages = _classifier_messages(event, filings, news)
    prompt = messages[0]["content"]

    system = (
        "You classify financial event catalysts. Read the EVENT, 8-K FILINGS, and NEWS "
        "context below, then output a single valid JSON object matching the schema in "
        "the prompt. No markdown fences. No prose before or after. JSON only."
    )
    full_prompt = system + "\n\n" + prompt

    with tempfile.NamedTemporaryFile("w+", suffix=".txt", delete=False) as f:
        out_path = f.name
    try:
        result = subprocess.run(
            ["codex", "exec", "--sandbox", "read-only",
             "-c", "approval_policy=\"never\"",
             "--skip-git-repo-check",
             "-o", out_path,
             full_prompt],
            capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        log.warning("catalog_codex_timeout", ticker=event.ticker, date=event.date.isoformat())
        return None
    except Exception as exc:
        log.warning("catalog_codex_invoke_failed", ticker=event.ticker, error=str(exc))
        return None

    if result.returncode != 0:
        log.warning("catalog_codex_nonzero", ticker=event.ticker, code=result.returncode,
                    stderr=result.stderr[:300])
        return None

    try:
        with open(out_path) as f:
            raw = f.read().strip()
    except Exception as exc:
        log.warning("catalog_codex_output_read_failed", error=str(exc))
        return None
    finally:
        with contextlib.suppress(OSError):
            os.unlink(out_path)

    # Strip code fences if present
    text = raw
    if text.startswith("```"):
        text = text.split("```", 2)[1] if "```" in text[3:] else text
        if text.startswith("json"):
            text = text[4:]
        text = text.strip("`\n ")
    # Sometimes codex adds prose before the JSON — find the first { and matching }
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        log.warning("catalog_codex_parse_failed", error=str(exc), text_head=raw[:300])
        return None

    return ClassificationResult(
        category=str(parsed.get("category", "other")),
        subcategory=str(parsed.get("subcategory", "")),
        confidence=str(parsed.get("confidence", "low")),
        article_relative_timing=str(parsed.get("article_relative_timing", "unclear")),
        brief_explanation=str(parsed.get("brief_explanation", "")),
        is_market_wide=bool(parsed.get("is_market_wide", False)),
        evidence_snippet=parsed.get("evidence_snippet"),
        model=model,
        input_tokens=0,    # Codex doesn't surface per-call token counts cleanly
        output_tokens=0,
        cost_usd=0.0,      # Subscription-billed, not per-token
    )


# Backwards-compat alias used by the runner / iteration helper.
def classify_with_claude(event, filings, news, *, model="gpt-5.5", **kw):
    """Kept for API symmetry; delegates to Codex (Sonnet not reachable without API key)."""
    return classify_with_codex(event, filings, news, model=model)


# --- 5. Storage --------------------------------------------------------------
def append_row_atomic(parquet_path: Path, row: dict) -> None:
    """Atomic-ish append: read existing, append, write to tmp, rename."""

    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    existing = pd.read_parquet(parquet_path) if parquet_path.exists() else pd.DataFrame()
    new_df = pd.concat([existing, pd.DataFrame([row])], ignore_index=True)
    tmp = parquet_path.with_suffix(parquet_path.suffix + ".tmp")
    new_df.to_parquet(tmp)
    tmp.replace(parquet_path)


def load_catalog(parquet_path: Path) -> pd.DataFrame:
    if not parquet_path.exists():
        return pd.DataFrame()
    return pd.read_parquet(parquet_path)


def already_classified(catalog: pd.DataFrame, ticker: str, event_date: date) -> bool:
    if catalog.empty:
        return False
    return ((catalog["ticker"] == ticker) & (catalog["date"] == event_date.isoformat())).any()


# --- 6. End-to-end one event --------------------------------------------------
def classify_one_event(
    event: LargeMoveEvent,
    *,
    model: str = "gpt-5.5",
    rate_limit_sleep_s: float = 0.5,
) -> dict | None:
    """Run one event end-to-end: 8-K fetch → news fetch → classify → return row dict."""

    filings = fetch_8k_for_event(event.ticker, event.date)
    time.sleep(rate_limit_sleep_s)
    news = fetch_alpaca_news_for_event(event.ticker, event.date)
    time.sleep(rate_limit_sleep_s)
    result = classify_with_codex(event, filings, news, model=model)
    if result is None:
        return None
    return {
        "ticker": event.ticker,
        "date": event.date.isoformat(),
        "daily_return": event.daily_return,
        "abs_return": event.abs_return,
        "direction": event.direction,
        "spy_return": event.spy_return,
        "spy_excess": event.spy_excess,
        "category": result.category,
        "subcategory": result.subcategory,
        "confidence": result.confidence,
        "article_relative_timing": result.article_relative_timing,
        "brief_explanation": result.brief_explanation,
        "is_market_wide": result.is_market_wide,
        "evidence_snippet": result.evidence_snippet,
        "n_filings_8k": len(filings),
        "n_news_articles": len(news),
        "model": result.model,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "cost_usd": result.cost_usd,
        "classified_at": datetime.now().isoformat(timespec="seconds"),
    }
