# News Web Spider — Proposal

Date: 2026-05-19
Status: draft proposal. Implementation in branch `claude/news-web-spider-camoufox`.
Owner: the maintainer (via Claude Code).

## Why

`brain/03_data_sources.md` lists a general web news stack as the planned discovery
layer, but only RSS/JSON-API adapters have shipped (Finnhub, Yahoo via yfinance,
Alpaca News, SEC EDGAR, Fed RSS). There is no adapter that can ingest news from
arbitrary publishers — exactly the layer the project needs for sentiment/event
density beyond Yahoo's narrow `yfinance` slice.

This is the missing piece between "we get whatever RSS feeds give us" and
"we have an evidence base broad enough to support honest event studies."

## Scope

V0 is intentionally narrow:

- **Tickers**: SPY and QQQ only. No single-name 8-K equivalent here; SEC EDGAR
  already covers that lane.
- **Sources**: 2–3 broad-market RSS feeds, e.g. MarketWatch top stories, CNBC
  markets. Configurable list, no hard-coded magic.
- **Relevance filter**: keep an article only if its title or summary mentions
  SPY, QQQ, S&P, Nasdaq, "the market", or a small curated keyword list.
- **Output**: same `Event` records the other normalizers produce, with
  `source` set to the publisher domain and `asset_scope=["index"]`.

V0 explicitly does *not* do:

- Single-name news (Finnhub / SEC EDGAR / Alpaca News already cover that).
- Paywall bypass. If a publisher is paywalled, we skip it.
- LLM enrichment. That belongs in a separate worker downstream.
- Historical backfill. Same 14-ish day window as the other adapters until the
  lookback-days work lands.

## Approach: build on Scrapling, not bare Camoufox

`pyproject.toml` already lists `scrapling[fetchers] @ git+...` as a core
dependency. Scrapling's `StealthyFetcher` is a Camoufox-backed stealth browser
under the hood. We get Camoufox without adding it as a new top-level dep, and
we stay consistent with the existing adapters that also use Scrapling.

Two-stage flow per source:

1. **Discovery**: pull the RSS feed with Scrapling's plain `Fetcher` (no
   stealth needed — RSS is public). Parse it with stdlib `xml.etree`. Same
   approach the existing Fed adapter takes.
2. **Article body**: for each candidate item, fetch the article page with
   `StealthyFetcher` only if the publisher is on the `requires_stealth` list.
   Otherwise use plain `Fetcher`. Extract the article body with Scrapling's
   selector API.

## Polite-scraping discipline (non-negotiable)

The project's north star says scraping should be *"reliable, polite, logged,
and maintainable."* Camoufox via Scrapling is by design *unobservable*, which
is opposite of polite. To keep this from drifting:

- **Respect `robots.txt`.** Check before first fetch per host. Cache the
  result for 24h.
- **Rate-limit**: max 1 request per host every 3 seconds.
- **Identify ourselves**: set a real `From:` header with the contact email
  from `TRADER_SEC_USER_AGENT` (same pattern SEC EDGAR uses).
- **Log every fetch**: URL, status, latency, bytes — using `structlog` like
  the other adapters.
- **No JS execution** for sources where plain `Fetcher` works. Stealth is
  for last resort, not default.
- **Cache article body on disk** under `data/raw/web/<host>/<sha1>.html` so
  re-runs don't re-hit the publisher. Gitignored.

## Failure semantics

Match the existing adapter convention: any source-level failure is logged
and returns `[]`. One broken publisher must not break a run. See
`runner._safe_fetch_source` for the wrapper.

## Tests

- Mock the network at the `Fetcher`/`StealthyFetcher` boundary — no real
  publishers hit in CI.
- Use checked-in HTML fixtures for the article-extraction path. Two
  fixtures: one RSS feed, one article page.
- Cover: empty feed, malformed feed, article missing body, article with
  paywall marker, relevance filter rejection.

## What this unblocks

- More events in `news_events` → less anemic event-window reports.
- A real source-credibility ladder: SEC EDGAR (0.95) > Fed (0.95) > major
  outlets (0.7) > tabloid/blog (0.4) > social (0.2).
- The "X via Apify" lane (`brain/03_data_sources.md`) can copy this
  adapter's polite-scraping shape later.

## Open questions for the maintainer

1. Is the source list above acceptable, or do you have specific publishers
   you'd want first?
2. Are you OK with `StealthyFetcher` (Camoufox) being used in production
   trading data path, given it's "stealth by design"? Or should we restrict
   it to research backfill only?
3. Should this adapter run on the same `fetch-events` cadence, or have its
   own command (e.g. `trader-daily fetch-web-news`)?
