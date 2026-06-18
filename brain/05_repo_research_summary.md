# Repo Research Summary

The full 62-repo dossier is saved at:

```text
research/trading-repos/TRADING_REPO_DOSSIER.md
```

The raw metadata and collection script are also preserved in `research/trading-repos/`.

## Recommended Stack From Research

### News Discovery And Extraction

- `feedparser`
- `GNews`
- `trafilatura`
- `newspaper4k` fallback
- `news-please` for heavier crawl jobs

### SEC

- `sec-edgar-downloader`

### Market And Options Data

- Alpaca as primary execution and first market data integration
- Polygon as optional upgrade/complement for serious options data
- `yfinance` only for cheap research fallback

### Entity And Reference Data

- `FinanceDatabase`
- custom ticker/entity resolver

### Sentiment And Classification

- `FinBERT`
- `vaderSentiment`
- LLM classification with strict JSON output and evidence pointers

### RAG And Evidence Store

- `llama_index`
- `pgvector` for v1
- Qdrant later if vector search needs to scale separately

### Backtesting

- `vectorbt` for fast signal sweeps
- `ffn` for analytics
- custom event-window backtests
- avoid AGPL dependencies in production without legal review

### Execution

- Direct Alpaca wrapper first
- Lumibot only if license and dependency tradeoffs are acceptable

## Strong Opinion

Do not copy a full trading-agent repo and let it trade.

Use those repos as inspiration for analyst workflows, debate patterns, and report generation. The real edge comes from clean data, exact timestamps, tested signals, and risk discipline.

