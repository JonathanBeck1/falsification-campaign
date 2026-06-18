# Universal Scraper Data Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Each work package should be built on its own branch and opened as its own PR unless the orchestrator explicitly merges packages together.

**Goal:** Build a production-grade, continuously scheduled, auditable scraping and ingestion layer that turns public or authorized authenticated web data into normalized, point-in-time trading events.

**Architecture:** Source configs define what to fetch, when to fetch it, how to authenticate if authorized, and how to parse it. Fetchers save raw documents first, parsers convert raw documents into normalized candidate records, classifiers/ticker mappers convert records into `news_events`, and outcome/replay systems test whether those events have edge. Raw evidence is never skipped because the system needs auditability and re-parsing.

**Tech Stack:** Python, SQLite, existing `Store` migration system, existing `source_fetches` ledger, Scrapling for web extraction where appropriate, browser-profile authenticated extraction for authorized sources only, pytest fixtures, Streamlit dashboard.

---

## Non-Negotiable Boundaries

- Authenticated scraping means using accounts, sessions, cookies, or browser profiles the operator is allowed to use.
- Do not build paywall bypass, CAPTCHA bypass, credential theft, bot-defense evasion, or deceptive traffic hiding.
- Do not commit cookies, browser profiles, session tokens, screenshots with secrets, or raw credentials.
- Store `observed_at` and `fetched_at` for every item. Without those timestamps, the data is not valid for point-in-time trading research.
- Always save raw evidence before parsing. Parsed events without raw artifacts are not acceptable for this system.
- No live trading, paid APIs, or LLM calls are required for this plan unless a later PR explicitly opts in.

## Target Data Flow

```text
source registry
  -> scheduler/job runner
  -> fetcher: rss | http | sitemap | browser_profile | api
  -> raw_documents table + raw artifact file
  -> parser/extractor
  -> canonical document records
  -> dedupe + ticker/entity mapping
  -> normalized news_events
  -> enrichment/scoring/outcome labels
  -> replay/edge reports/dashboard
```

## Branch And PR Rules

- Base every work package on latest `main` after pending PRs are merged.
- Use branch names like `codex/scraper-source-registry`.
- One work package per PR.
- Every PR must include tests and a short `brain/decisions/YYYY-MM-DD-*.md` note if it changes architecture.
- Generated raw data, SQLite files, cookies, and browser profiles stay ignored.

## Proposed File Map

These are the intended ownership boundaries. Subagents should not edit outside their package without telling the orchestrator.

| Area | Files |
|---|---|
| Source registry | `configs/sources.example.toml`, `src/trader/ingestion/source_registry.py`, `tests/financial/test_source_registry.py` |
| Raw document store | `src/trader/storage/migrations/m0004_raw_documents.py`, `src/trader/storage/store.py`, `tests/financial/test_raw_documents_store.py` |
| Fetcher contracts | `src/trader/ingestion/fetchers/base.py`, `src/trader/ingestion/fetchers/http.py`, `src/trader/ingestion/fetchers/rss.py`, `src/trader/ingestion/fetchers/browser_profile.py`, `tests/financial/test_fetchers_*.py` |
| Parser contracts | `src/trader/ingestion/parsers/base.py`, `src/trader/ingestion/parsers/article.py`, `src/trader/ingestion/parsers/rss.py`, `tests/financial/test_parsers_*.py` |
| Dedupe/canonicalization | `src/trader/ingestion/dedupe.py`, `tests/financial/test_document_dedupe.py` |
| Ticker/entity mapping | `src/trader/normalization/tickers.py`, `config/universes/*.yaml`, `tests/financial/test_ticker_mapping.py` |
| Scheduler/jobs | `src/trader/ingestion/jobs.py`, `src/trader/scheduler.py`, `src/trader/cli.py`, `tests/financial/test_ingestion_jobs.py` |
| First web adapters | `src/trader/adapters/news/businessinsider.py`, `src/trader/adapters/news/generic_article.py`, fixtures in `tests/fixtures/web/` |
| Dashboard | `apps/dashboard.py`, `tests/financial/test_dashboard_data.py` |

---

## Work Package 1: Source Registry

**Owner:** Subagent A  
**Branch:** `codex/scraper-source-registry`  
**Goal:** Create a typed registry that defines all scrape/API/feed sources and makes source behavior configurable.

**Files:**
- Modify: `configs/sources.example.toml`
- Create: `src/trader/ingestion/source_registry.py`
- Create: `tests/financial/test_source_registry.py`

### Requirements

The registry must support:

- `source_id`
- `enabled`
- `mode`: `rss`, `http`, `sitemap`, `browser_profile`, `api`
- `base_url`
- `schedule`
- `rate_limit_seconds`
- `requires_auth`
- `auth_profile`
- `parser`
- `universe`
- `allowed_domains`
- `max_items_per_run`
- `cache_ttl_seconds`

### Implementation Steps

- [ ] Add example config entries to `configs/sources.example.toml`.

Expected shape:

```toml
[[sources]]
source_id = "businessinsider_markets"
enabled = true
mode = "rss"
base_url = "https://www.businessinsider.com/sai/rss"
schedule = "*/5 * * * *"
rate_limit_seconds = 5
requires_auth = false
auth_profile = ""
parser = "rss_article"
universe = "core_us"
allowed_domains = ["businessinsider.com", "www.businessinsider.com"]
max_items_per_run = 50
cache_ttl_seconds = 300

[[sources]]
source_id = "authorized_example"
enabled = false
mode = "browser_profile"
base_url = "https://example.com/account/news"
schedule = "*/10 * * * *"
rate_limit_seconds = 10
requires_auth = true
auth_profile = "default"
parser = "generic_article"
universe = "core_us"
allowed_domains = ["example.com"]
max_items_per_run = 25
cache_ttl_seconds = 300
```

- [ ] Write tests for valid config loading.

Test cases:

```python
def test_source_registry_loads_enabled_sources(tmp_path):
    path = tmp_path / "sources.toml"
    path.write_text(
        """
        [[sources]]
        source_id = "businessinsider_markets"
        enabled = true
        mode = "rss"
        base_url = "https://www.businessinsider.com/sai/rss"
        schedule = "*/5 * * * *"
        rate_limit_seconds = 5
        requires_auth = false
        auth_profile = ""
        parser = "rss_article"
        universe = "core_us"
        allowed_domains = ["businessinsider.com"]
        max_items_per_run = 50
        cache_ttl_seconds = 300
        """,
        encoding="utf-8",
    )

    registry = load_source_registry(path)

    assert len(registry.enabled_sources()) == 1
    assert registry.get("businessinsider_markets").mode == "rss"
```

- [ ] Write tests for invalid modes and unsafe configs.

Expected failures:

```python
def test_source_registry_rejects_auth_without_profile(tmp_path):
    path = tmp_path / "sources.toml"
    path.write_text(
        """
        [[sources]]
        source_id = "bad_auth"
        enabled = true
        mode = "browser_profile"
        base_url = "https://example.com/news"
        schedule = "*/5 * * * *"
        rate_limit_seconds = 5
        requires_auth = true
        auth_profile = ""
        parser = "generic_article"
        universe = "core_us"
        allowed_domains = ["example.com"]
        max_items_per_run = 10
        cache_ttl_seconds = 300
        """,
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="auth_profile"):
        load_source_registry(path)
```

- [ ] Implement `SourceConfig`, `SourceRegistry`, and `load_source_registry`.
- [ ] Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/financial/test_source_registry.py -q
PYTHONPATH=src .venv/bin/python -m ruff check src/trader/ingestion/source_registry.py tests/financial/test_source_registry.py
```

- [ ] Commit:

```bash
git add configs/sources.example.toml src/trader/ingestion/source_registry.py tests/financial/test_source_registry.py
git commit -m "feat: add scraper source registry"
```

### Acceptance Criteria

- Config is typed and validated.
- Authenticated sources require named local profiles.
- Disabled sources load but do not run.
- Bad modes, missing domains, and invalid rates fail fast.

---

## Work Package 2: Raw Document Store

**Owner:** Subagent B  
**Branch:** `codex/raw-document-store`  
**Goal:** Persist every fetched page/feed/API response as raw evidence before parsing.

**Files:**
- Create: `src/trader/storage/migrations/m0004_raw_documents.py`
- Modify: `src/trader/storage/store.py`
- Create: `tests/financial/test_raw_documents_store.py`

### Schema

Create table `raw_documents`:

```sql
CREATE TABLE IF NOT EXISTS raw_documents (
    raw_document_id     TEXT PRIMARY KEY,
    source_id           TEXT NOT NULL,
    source_url          TEXT NOT NULL,
    canonical_url       TEXT,
    fetched_at          TEXT NOT NULL,
    observed_at         TEXT NOT NULL,
    status_code         INTEGER,
    content_type        TEXT,
    content_hash        TEXT NOT NULL,
    storage_path        TEXT,
    title               TEXT,
    published_at        TEXT,
    parser              TEXT,
    parse_status        TEXT NOT NULL DEFAULT 'pending',
    error               TEXT,
    metadata_json       TEXT NOT NULL DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_id, content_hash)
);
```

Indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_raw_documents_source_time
ON raw_documents(source_id, observed_at);

CREATE INDEX IF NOT EXISTS idx_raw_documents_url
ON raw_documents(source_url);

CREATE INDEX IF NOT EXISTS idx_raw_documents_parse_status
ON raw_documents(parse_status);
```

### Store Helpers

Add methods:

```python
def save_raw_document(self, doc: RawDocumentInput) -> str:
    ...

def get_raw_document(self, raw_document_id: str) -> dict[str, Any] | None:
    ...

def list_raw_documents(
    self,
    *,
    source_id: str | None = None,
    parse_status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    ...

def mark_raw_document_parsed(
    self,
    raw_document_id: str,
    *,
    parse_status: str,
    title: str | None = None,
    published_at: str | None = None,
    canonical_url: str | None = None,
    error: str | None = None,
) -> None:
    ...
```

### Tests

- [ ] Test migration advances latest version.
- [ ] Test `save_raw_document` is idempotent by `(source_id, content_hash)`.
- [ ] Test parse status updates.
- [ ] Test filtering by source and status.

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/financial/test_raw_documents_store.py -q
PYTHONPATH=src .venv/bin/python -m ruff check src/trader/storage tests/financial/test_raw_documents_store.py
```

Commit:

```bash
git add src/trader/storage/migrations/m0004_raw_documents.py src/trader/storage/store.py tests/financial/test_raw_documents_store.py
git commit -m "feat: add raw document store"
```

### Acceptance Criteria

- Every raw fetch can be stored before parsing.
- Duplicate content does not create duplicate rows.
- Raw documents can be listed for reprocessing.

---

## Work Package 3: Fetcher Layer

**Owner:** Subagent C  
**Branch:** `codex/scraper-fetchers`  
**Goal:** Add fetcher interfaces for public feeds/pages and authorized browser-profile pages.

**Files:**
- Create: `src/trader/ingestion/fetchers/__init__.py`
- Create: `src/trader/ingestion/fetchers/base.py`
- Create: `src/trader/ingestion/fetchers/http.py`
- Create: `src/trader/ingestion/fetchers/rss.py`
- Create: `src/trader/ingestion/fetchers/browser_profile.py`
- Create: `tests/financial/test_fetchers.py`

### Contracts

Define:

```python
@dataclass(frozen=True)
class FetchRequest:
    source_id: str
    url: str
    mode: str
    allowed_domains: tuple[str, ...]
    timeout_seconds: int = 30
    auth_profile: str | None = None


@dataclass(frozen=True)
class FetchResult:
    source_id: str
    url: str
    final_url: str
    fetched_at: datetime
    status_code: int | None
    content_type: str
    body: str
    metadata: dict[str, Any]
```

### Required Behavior

- Validate URL host is in `allowed_domains`.
- HTTP/RSS fetchers use normal request paths, no stealth by default.
- Browser-profile fetcher uses a local profile path configured outside git.
- Browser-profile fetcher must return a clear `NeedsLogin`/`AuthExpired` style error when the session is not usable.
- Fetchers do not parse trading events.
- Fetchers do not write to DB directly; ingestion jobs do.

### Tests

- [ ] Host allowlist blocks unexpected domains.
- [ ] HTTP fetcher handles 200, 404, timeout.
- [ ] RSS fetcher returns feed body without parsing it.
- [ ] Browser-profile fetcher refuses missing profile path.
- [ ] Browser-profile fetcher never prints or stores cookies.

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/financial/test_fetchers.py -q
PYTHONPATH=src .venv/bin/python -m ruff check src/trader/ingestion/fetchers tests/financial/test_fetchers.py
```

Commit:

```bash
git add src/trader/ingestion/fetchers tests/financial/test_fetchers.py
git commit -m "feat: add scraper fetcher layer"
```

### Acceptance Criteria

- Fetchers are swappable by source mode.
- Authenticated scraping is supported only through explicit local profiles.
- No secrets are stored or logged.

---

## Work Package 4: Parser And Extraction Layer

**Owner:** Subagent D  
**Branch:** `codex/document-parsers`  
**Goal:** Convert raw fetched content into canonical article/feed records.

**Files:**
- Create: `src/trader/ingestion/parsers/__init__.py`
- Create: `src/trader/ingestion/parsers/base.py`
- Create: `src/trader/ingestion/parsers/rss.py`
- Create: `src/trader/ingestion/parsers/article.py`
- Create fixtures: `tests/fixtures/web/sample_feed.xml`, `tests/fixtures/web/businessinsider_article.html`
- Create: `tests/financial/test_document_parsers.py`

### Contracts

```python
@dataclass(frozen=True)
class ParsedDocument:
    source_id: str
    source_url: str
    canonical_url: str
    title: str
    published_at: datetime | None
    author: str | None
    text: str
    links: tuple[str, ...]
    metadata: dict[str, Any]
```

### Required Behavior

- RSS parser extracts item URLs, titles, summaries, and timestamps.
- Article parser extracts title, published timestamp where available, and main body text.
- Parser returns empty body status for paywall/blocked/empty pages.
- Parser never fabricates timestamps.
- Parser keeps `published_at=None` if not found.

### Tests

- [ ] RSS fixture yields expected items.
- [ ] Article fixture extracts title/body.
- [ ] Missing timestamp stays `None`.
- [ ] Paywall marker returns blocked status.
- [ ] Broken HTML does not crash the run.

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/financial/test_document_parsers.py -q
PYTHONPATH=src .venv/bin/python -m ruff check src/trader/ingestion/parsers tests/financial/test_document_parsers.py
```

Commit:

```bash
git add src/trader/ingestion/parsers tests/fixtures/web tests/financial/test_document_parsers.py
git commit -m "feat: add document parser layer"
```

### Acceptance Criteria

- Raw documents can be re-parsed without re-fetching.
- Parsers produce stable canonical records.
- Parser failures are explicit and non-fatal.

---

## Work Package 5: Dedupe And Canonicalization

**Owner:** Subagent E  
**Branch:** `codex/document-dedupe`  
**Goal:** Prevent the same article/story from becoming multiple trading events.

**Files:**
- Create: `src/trader/ingestion/dedupe.py`
- Create: `tests/financial/test_document_dedupe.py`

### Required Behavior

Deduplicate using:

- normalized canonical URL
- content hash
- title similarity for same-source near duplicates
- published timestamp proximity

Expose:

```python
def normalize_url(url: str) -> str:
    ...

def content_hash(text: str) -> str:
    ...

def story_fingerprint(title: str, published_at: datetime | None, source: str) -> str:
    ...

def is_probable_duplicate(a: ParsedDocument, b: ParsedDocument) -> bool:
    ...
```

### Tests

- [ ] Tracking params are stripped.
- [ ] URL fragments are stripped.
- [ ] Same title/source/day is duplicate.
- [ ] Same generic title across different sources is not automatically duplicate.
- [ ] Different articles from the same source are not collapsed.

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/financial/test_document_dedupe.py -q
PYTHONPATH=src .venv/bin/python -m ruff check src/trader/ingestion/dedupe.py tests/financial/test_document_dedupe.py
```

Commit:

```bash
git add src/trader/ingestion/dedupe.py tests/financial/test_document_dedupe.py
git commit -m "feat: add document dedupe utilities"
```

### Acceptance Criteria

- Re-fetching the same article does not create repeated events.
- Syndicated articles can be identified for later source-quality scoring.

---

## Work Package 6: Universe And Ticker Mapping

**Owner:** Subagent F  
**Branch:** `codex/universe-ticker-mapping`  
**Goal:** Create a reusable ticker/entity mapping layer so scraped text can become ticker-scoped events.

**Files:**
- Create: `config/universes/core_us.yaml`
- Create: `config/universes/sector_etfs.yaml`
- Create: `src/trader/data/universe.py`
- Create: `src/trader/normalization/tickers.py`
- Create: `tests/financial/test_universe.py`
- Create: `tests/financial/test_ticker_mapping.py`

### Required Behavior

Universe loader:

- loads YAML
- uppercases symbols
- dedupes symbols
- rejects invalid symbols

Ticker mapper:

- exact ticker detection for `$AAPL`, `(AAPL)`, `NASDAQ:AAPL`
- company alias detection for curated names
- ambiguity guardrails for words like `ON`, `CAT`, `ALL`, `ARE`
- index exposure mapping for broad-market stories

### Tests

- [ ] Universe loader dedupes symbols.
- [ ] `$AAPL` maps to `AAPL`.
- [ ] `Apple Inc.` maps to `AAPL`.
- [ ] `apple pie` does not map to `AAPL`.
- [ ] `market rally` maps to index exposure `SPY`, `QQQ` but no primary single-name ticker.

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/financial/test_universe.py tests/financial/test_ticker_mapping.py -q
PYTHONPATH=src .venv/bin/python -m ruff check src/trader/data src/trader/normalization/tickers.py tests/financial/test_universe.py tests/financial/test_ticker_mapping.py
```

Commit:

```bash
git add config/universes src/trader/data src/trader/normalization/tickers.py tests/financial/test_universe.py tests/financial/test_ticker_mapping.py
git commit -m "feat: add universe and ticker mapping"
```

### Acceptance Criteria

- News can be mapped to tickers without blindly trusting all uppercase words.
- Ambiguous tickers are handled conservatively.

---

## Work Package 7: Ingestion Job Runner

**Owner:** Subagent G  
**Branch:** `codex/scraper-ingestion-jobs`  
**Goal:** Wire source registry, fetchers, raw store, parsers, dedupe, and normalization into one job runner.

**Files:**
- Create: `src/trader/ingestion/jobs.py`
- Modify: `src/trader/cli.py`
- Modify: `src/trader/ingestion/events.py` if reuse is needed
- Create: `tests/financial/test_ingestion_jobs.py`

### CLI

Add:

```bash
trader scrape-source --source businessinsider_markets
trader scrape-sources --enabled-only
trader parse-raw-documents --limit 100
```

### Required Behavior

- `scrape-source`:
  - loads one source config
  - fetches source
  - stores raw document
  - records source fetch ledger row
  - does not trade

- `scrape-sources`:
  - loops enabled sources
  - one source failure does not stop others
  - respects `max_items_per_run`

- `parse-raw-documents`:
  - processes pending raw docs
  - updates parse status
  - creates normalized `news_events`

### Tests

- [ ] Source success stores raw document and fetch ledger row.
- [ ] Source failure stores fetch error and continues.
- [ ] Parse command creates `news_events`.
- [ ] Duplicate raw docs do not create duplicate events.
- [ ] Live mode does not matter; these commands never place orders.

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/financial/test_ingestion_jobs.py -q
PYTHONPATH=src .venv/bin/python -m ruff check src/trader/ingestion/jobs.py src/trader/cli.py tests/financial/test_ingestion_jobs.py
```

Commit:

```bash
git add src/trader/ingestion/jobs.py src/trader/cli.py tests/financial/test_ingestion_jobs.py
git commit -m "feat: add scraper ingestion jobs"
```

### Acceptance Criteria

- One command can fetch raw data.
- One command can parse raw data into events.
- Failures are visible in existing source health patterns.

---

## Work Package 8: First Real Web Source Adapters

**Owner:** Subagent H  
**Branch:** `codex/first-web-source-adapters`  
**Goal:** Add concrete adapters for sources we can use immediately.

**Files:**
- Create: `src/trader/adapters/news/businessinsider.py`
- Create: `src/trader/adapters/news/generic_article.py`
- Add fixtures under `tests/fixtures/web/`
- Create: `tests/financial/test_businessinsider_adapter.py`

### First Sources

Start with:

- Business Insider markets feed/articles
- CNBC market RSS/articles if not already fully covered by existing web adapter
- MarketWatch RSS/articles if not already fully covered by existing web adapter

### Required Behavior

- Use RSS discovery when available.
- Fetch article page only when useful.
- Skip blocked/paywalled article bodies cleanly.
- Emit normalized documents/events using existing `Event` shape.
- Keep evidence pointers to raw documents.

### Tests

- [ ] Business Insider RSS fixture produces article candidates.
- [ ] Article fixture extracts text.
- [ ] Relevance filter keeps market/ticker stories.
- [ ] Relevance filter rejects unrelated lifestyle stories.
- [ ] Adapter returns empty list on broken feed.

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/financial/test_businessinsider_adapter.py -q
PYTHONPATH=src .venv/bin/python -m ruff check src/trader/adapters/news tests/financial/test_businessinsider_adapter.py
```

Commit:

```bash
git add src/trader/adapters/news/businessinsider.py src/trader/adapters/news/generic_article.py tests/fixtures/web tests/financial/test_businessinsider_adapter.py
git commit -m "feat: add first web source adapters"
```

### Acceptance Criteria

- Business Insider can be collected as a real source.
- New source adapters follow the raw-document-first contract.

---

## Work Package 9: Scheduler And Continuous Collection

**Owner:** Subagent I  
**Branch:** `codex/continuous-data-scheduler`  
**Goal:** Run scraping and parsing jobs continuously on a safe cadence.

**Files:**
- Modify: `src/trader/scheduler.py`
- Create: `src/trader/ingestion/schedules.py`
- Modify: `src/trader/cli.py`
- Create: `tests/financial/test_continuous_scheduler.py`

### CLI

Add or extend:

```bash
trader data-scheduler --sources configs/sources.toml
trader data-scheduler --once
```

### Required Behavior

- Run source jobs on configured schedule.
- Run parsing shortly after fetching.
- Apply per-source backoff after errors.
- Write source health rows.
- Exit cleanly on keyboard interrupt.
- Never call live broker.

### Tests

- [ ] `--once` executes each due enabled source once.
- [ ] Disabled sources are skipped.
- [ ] Failed source gets backoff.
- [ ] Parser job runs after successful fetch.
- [ ] Scheduler does not call `runner.run_one_day`.

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/financial/test_continuous_scheduler.py -q
PYTHONPATH=src .venv/bin/python -m ruff check src/trader/scheduler.py src/trader/ingestion/schedules.py tests/financial/test_continuous_scheduler.py
```

Commit:

```bash
git add src/trader/scheduler.py src/trader/ingestion/schedules.py src/trader/cli.py tests/financial/test_continuous_scheduler.py
git commit -m "feat: add continuous data scheduler"
```

### Acceptance Criteria

- A local command can collect data continuously.
- Jobs are observable and recoverable.

---

## Work Package 10: Dashboard Data Operations View

**Owner:** Subagent J  
**Branch:** `codex/dashboard-data-ops`  
**Goal:** Make the dashboard show whether the data engine is healthy.

**Files:**
- Modify: `apps/dashboard.py`
- Modify/create tests near `tests/financial/test_dashboard_data.py`

### Dashboard Sections

Add:

- Source registry table
- Latest fetch status
- Raw document counts by source/status
- News event counts by source/event type
- Data gaps panel
- Last scheduler run
- Auth profile health: `ok`, `needs_login`, `missing`, without exposing secrets

### Tests

- [ ] Dashboard data helper returns raw document counts.
- [ ] Dashboard data helper returns source health.
- [ ] Missing auth profile is shown as `needs_login` or `missing`, not as exception text.

Run:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/financial/test_dashboard_data.py -q
PYTHONPATH=src .venv/bin/python -m ruff check apps/dashboard.py tests/financial/test_dashboard_data.py
```

Commit:

```bash
git add apps/dashboard.py tests/financial/test_dashboard_data.py
git commit -m "feat: add data operations dashboard"
```

### Acceptance Criteria

- User can see what is being scraped and what is failing.
- Auth/session problems are visible without leaking secrets.

---

## Integration Sequence

### Phase 1: Foundations

Merge in this order:

1. Work Package 1: Source Registry
2. Work Package 2: Raw Document Store
3. Work Package 3: Fetcher Layer
4. Work Package 4: Parser Layer
5. Work Package 5: Dedupe
6. Work Package 6: Universe/Ticker Mapping

### Phase 2: Working Pipeline

Merge in this order:

7. Work Package 7: Ingestion Job Runner
8. Work Package 8: First Web Source Adapters
9. Work Package 9: Scheduler
10. Work Package 10: Dashboard Data Ops

### Phase 3: Trading Research Follow-Ups

Do not start these until the scraper engine is collecting:

- Historical SEC filing backfill
- Event outcome labels for scraped events
- Event replay using only point-in-time observed events
- Edge report V2 with sample-size and false-discovery warnings

---

## Parallel Dispatch Plan

Safe to start immediately in parallel after latest `main` is clean:

- Subagent A: Source Registry
- Subagent B: Raw Document Store
- Subagent D: Parser Layer
- Subagent F: Universe/Ticker Mapping

Start after Source Registry lands:

- Subagent C: Fetcher Layer

Start after Raw Store + Fetchers + Parsers land:

- Subagent G: Ingestion Job Runner
- Subagent H: First Web Source Adapters

Start after Job Runner lands:

- Subagent I: Scheduler
- Subagent J: Dashboard Data Ops

---

## Orchestrator Responsibilities

The main orchestrator should:

- Keep branches separate.
- Prevent two subagents from editing the same file at the same time.
- Review every PR for scope creep.
- Run full verification after each merge:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
PYTHONPATH=src .venv/bin/python -m ruff check src/trader tests/financial apps
```

- Keep generated data out of git.
- Update `brain/03_data_sources.md`, `brain/04_scraper_strategy.md`, and this plan when implementation choices change.

---

## Final Acceptance Criteria

The scraper data engine is usable when all of this is true:

- `trader scrape-sources --enabled-only` stores raw documents.
- `trader parse-raw-documents --limit 100` creates normalized `news_events`.
- `trader data-scheduler --once` runs fetch + parse without broker or LLM calls.
- Dashboard shows source health, raw document inventory, event counts, and auth/session issues.
- Full tests pass.
- Ruff is clean.
- No cookies, credentials, raw profiles, or generated SQLite/raw artifacts are tracked by git.

