# Data Sources

## Trading Sources

### X via Apify

Purpose: social/news velocity, breaking narratives, influencer/news account monitoring.

Status: user has identified a cheaper Apify scraper compared with X API pricing.

Best use: discovery layer and sentiment/momentum source.

Risk: noisy, manipulation-heavy, entity mapping is difficult.

### News Websites

Purpose: event discovery and article evidence.

Preferred stack:

- `feedparser` for RSS/Atom discovery
- `GNews` for broad Google News discovery
- `trafilatura` for article extraction
- `newspaper4k` fallback parser
- `news-please` for heavier batch crawling

Risk: paywalls, publisher template changes, duplicate syndication, lag.

### SEC EDGAR

Purpose: high-credibility filings and corporate events.

Preferred stack: `sec-edgar-downloader`.

Risk: less real-time than social/news; must respect SEC fair-access rules.

### Alpaca

Purpose: market data, paper trading, eventual execution.

Status: planned paid market-data plan.

Best use: first execution integration and core market snapshots.

Risk: confirm exact options data/execution support for the chosen plan and SDK.

### Polygon

Purpose: production-grade market/options/news data alternative or complement.

Best use: serious options chain and historical data if Alpaca data is insufficient.

Risk: cost, rate limits, plan restrictions.

## Source Admission Rule

A source is allowed into the production pipeline only after we know:

- what fields it returns
- how fresh it is
- how often it fails
- what it costs
- what license or terms apply
- how it maps to our event schema

