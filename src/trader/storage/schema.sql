-- Stock Trader v0 schema. Single source of truth for all run state.
-- Designed for SQLite; types are loose by design.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id   TEXT PRIMARY KEY,           -- e.g. "2026-05-18T16:15:00Z:QQQ"
    trade_date    TEXT NOT NULL,              -- YYYY-MM-DD (the *decision* date)
    ticker        TEXT NOT NULL,
    payload_json  TEXT NOT NULL,              -- serialized DailySnapshot
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_snapshots_date ON snapshots(trade_date);

CREATE TABLE IF NOT EXISTS decisions (
    decision_id   TEXT PRIMARY KEY,
    snapshot_id   TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    brain         TEXT NOT NULL,              -- signal name: "ClassicalBrain", "HybridBrain", ...
    action        TEXT NOT NULL,              -- "BUY" | "SELL" | "HOLD"
    target_pct    REAL NOT NULL,              -- target portfolio weight in [0, 1]
    confidence    REAL,
    reasoning     TEXT,
    llm_cost_usd  REAL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_decisions_brain ON decisions(brain);
CREATE INDEX IF NOT EXISTS idx_decisions_snapshot ON decisions(snapshot_id);

CREATE TABLE IF NOT EXISTS orders (
    client_order_id TEXT PRIMARY KEY,          -- idempotency key sent to Alpaca
    decision_id     TEXT REFERENCES decisions(decision_id),
    brain           TEXT NOT NULL,
    ticker          TEXT NOT NULL,
    side            TEXT NOT NULL,             -- "buy" | "sell"
    qty             REAL NOT NULL,
    order_type      TEXT NOT NULL,             -- "market" | "limit"
    limit_price     REAL,
    submitted_at    TEXT NOT NULL DEFAULT (datetime('now')),
    alpaca_order_id TEXT,
    status          TEXT NOT NULL DEFAULT 'submitted'
);
CREATE INDEX IF NOT EXISTS idx_orders_brain ON orders(brain);

CREATE TABLE IF NOT EXISTS fills (
    fill_id          TEXT PRIMARY KEY,
    client_order_id  TEXT NOT NULL REFERENCES orders(client_order_id),
    filled_qty       REAL NOT NULL,
    filled_avg_price REAL NOT NULL,
    filled_at        TEXT NOT NULL,
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Per-brain virtual portfolio so we can compare brains without splitting Alpaca accounts.
CREATE TABLE IF NOT EXISTS brain_portfolios (
    brain          TEXT PRIMARY KEY,
    cash           REAL NOT NULL,
    position_qty   REAL NOT NULL DEFAULT 0,
    avg_cost       REAL NOT NULL DEFAULT 0,
    realized_pnl   REAL NOT NULL DEFAULT 0,
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS brain_equity_curve (
    brain      TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    equity     REAL NOT NULL,                  -- cash + position_qty * close
    PRIMARY KEY (brain, trade_date)
);

CREATE TABLE IF NOT EXISTS llm_calls (
    call_id      TEXT PRIMARY KEY,
    decision_id  TEXT REFERENCES decisions(decision_id),
    brain        TEXT NOT NULL,
    model        TEXT NOT NULL,
    prompt_hash  TEXT NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cached_tokens INTEGER DEFAULT 0,
    cost_usd     REAL,
    latency_ms   INTEGER,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Internal/system event log (kill switch trips, brain errors, etc.).
-- NOT to be confused with the normalized news_events table below.
CREATE TABLE IF NOT EXISTS events (
    event_id    TEXT PRIMARY KEY,
    level       TEXT NOT NULL,                 -- "info" | "warn" | "error" | "kill"
    source      TEXT NOT NULL,                 -- module name
    message     TEXT NOT NULL,
    payload_json TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_events_level ON events(level);

-- Normalized news/filing/macro events per brain/08_news_event_schema.md.
-- Source adapters -> normalization layer -> this table -> signals & research.
-- Named news_events to avoid colliding with the system event log above.
CREATE TABLE IF NOT EXISTS news_events (
    event_id              TEXT PRIMARY KEY,
    source                TEXT NOT NULL,
    source_url            TEXT NOT NULL DEFAULT '',
    title                 TEXT NOT NULL,
    summary               TEXT NOT NULL DEFAULT '',
    published_at          TEXT NOT NULL,          -- UTC ISO-8601 text with +00:00 offset
    observed_at           TEXT NOT NULL,          -- first observed; preserved across duplicate upserts
    last_seen_at          TEXT NOT NULL DEFAULT (datetime('now')), -- latest sighting; store writes canonical UTC text
    ingested_at           TEXT NOT NULL DEFAULT (datetime('now')), -- store writes canonical UTC text
    classified_at         TEXT,                   -- UTC ISO-8601 text with +00:00 offset
    event_type            TEXT NOT NULL DEFAULT 'other',
    sentiment             TEXT NOT NULL DEFAULT 'neutral',
    sentiment_score       REAL NOT NULL DEFAULT 0.0,
    urgency               TEXT NOT NULL DEFAULT 'normal',
    novelty_score         REAL NOT NULL DEFAULT 0.0,
    source_credibility    REAL NOT NULL DEFAULT 0.5,
    -- JSON-serialized complex fields (kept as TEXT for SQLite portability)
    entities_json         TEXT NOT NULL DEFAULT '[]',
    asset_scope_json      TEXT NOT NULL DEFAULT '[]',
    index_exposure_json   TEXT NOT NULL DEFAULT '[]',
    evidence_json         TEXT NOT NULL DEFAULT '[]',
    model_outputs_json    TEXT NOT NULL DEFAULT '[]',
    raw_artifact_path     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_news_events_published ON news_events(published_at);
CREATE INDEX IF NOT EXISTS idx_news_events_source    ON news_events(source);
CREATE INDEX IF NOT EXISTS idx_news_events_type      ON news_events(event_type);

-- Research cycle run manifests and artifacts.
-- These are audit records for research-only evidence runs, not trading signals.
CREATE TABLE IF NOT EXISTS research_runs (
    run_id              TEXT PRIMARY KEY,
    started_at          TEXT NOT NULL,
    finished_at         TEXT,
    status              TEXT NOT NULL,
    command_json        TEXT NOT NULL DEFAULT '{}',
    benchmark           TEXT NOT NULL DEFAULT 'SPY',
    entry_time          TEXT NOT NULL DEFAULT 'observed_at',
    horizons            TEXT NOT NULL DEFAULT '',
    group_by            TEXT NOT NULL DEFAULT '',
    since               TEXT,
    until               TEXT,
    data_provider       TEXT NOT NULL DEFAULT 'yahoo',
    events_before       INTEGER NOT NULL DEFAULT 0,
    events_after        INTEGER NOT NULL DEFAULT 0,
    enriched_count      INTEGER NOT NULL DEFAULT 0,
    rejected_count      INTEGER NOT NULL DEFAULT 0,
    candidate_count     INTEGER NOT NULL DEFAULT 0,
    outcome_report_path TEXT NOT NULL DEFAULT '',
    review_report_path  TEXT NOT NULL DEFAULT '',
    manifest_path       TEXT NOT NULL DEFAULT '',
    error               TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_research_runs_started ON research_runs(started_at);
CREATE INDEX IF NOT EXISTS idx_research_runs_status ON research_runs(status);

CREATE TABLE IF NOT EXISTS research_run_artifacts (
    artifact_id   TEXT PRIMARY KEY,
    run_id        TEXT NOT NULL REFERENCES research_runs(run_id) ON DELETE CASCADE,
    artifact_type TEXT NOT NULL,
    path          TEXT NOT NULL,
    sha256        TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_research_run_artifacts_run ON research_run_artifacts(run_id);

-- Durable source fetch ledger for source-quality review and backfill auditing.
CREATE TABLE IF NOT EXISTS source_fetches (
    fetch_id        TEXT PRIMARY KEY,
    source          TEXT NOT NULL,
    attempted_at    TEXT NOT NULL,
    finished_at     TEXT,
    status          TEXT NOT NULL,
    item_count      INTEGER NOT NULL DEFAULT 0,
    persisted_count INTEGER NOT NULL DEFAULT 0,
    lookback_days   INTEGER,
    latency_ms      INTEGER,
    error           TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_source_fetches_source_time ON source_fetches(source, attempted_at);
CREATE INDEX IF NOT EXISTS idx_source_fetches_status ON source_fetches(status);

-- Research-only paper intent ledger. These rows are proposed/simulated order
-- plans, not broker-submitted orders.
CREATE TABLE IF NOT EXISTS paper_trade_intents (
    intent_id           TEXT PRIMARY KEY,
    event_id            TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    ticker              TEXT NOT NULL,
    direction           TEXT NOT NULL,
    candidate_score     REAL NOT NULL,
    confidence          REAL NOT NULL,
    proposed_action     TEXT NOT NULL,
    proposed_target_pct REAL NOT NULL,
    risk_status         TEXT NOT NULL,
    risk_reason         TEXT NOT NULL DEFAULT '',
    final_action        TEXT NOT NULL DEFAULT 'HOLD',
    final_qty           REAL NOT NULL DEFAULT 0,
    simulated_order_id  TEXT NOT NULL DEFAULT '',
    status              TEXT NOT NULL DEFAULT 'staged',
    source              TEXT NOT NULL DEFAULT '',
    event_type          TEXT NOT NULL DEFAULT '',
    title               TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_paper_trade_intents_created ON paper_trade_intents(created_at);
CREATE INDEX IF NOT EXISTS idx_paper_trade_intents_status ON paper_trade_intents(status);
CREATE INDEX IF NOT EXISTS idx_paper_trade_intents_event ON paper_trade_intents(event_id);

-- Retrieval sidecar for point-in-time similar-event lookup.
-- Canonical news_events rows stay immutable; retrieval freshness is recorded here.
CREATE TABLE IF NOT EXISTS event_retrievals (
    retrieval_id TEXT PRIMARY KEY,
    event_id     TEXT NOT NULL REFERENCES news_events(event_id) ON DELETE CASCADE,
    retrieved_at TEXT NOT NULL,                   -- UTC ISO-8601 text with +00:00 offset
    query_hash   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_event_retrievals_event_time ON event_retrievals(event_id, retrieved_at);
