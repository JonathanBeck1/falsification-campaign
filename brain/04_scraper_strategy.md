# Scraper Strategy

## Principle

Scrapers should be adapters, not one-off scripts.

Each adapter should have:

- a source name
- a clear input
- a raw output artifact
- normalized records
- logs
- tests around normalization
- documented setup

## Preferred Website Ingestion Order

1. Official API or feed if available and affordable.
2. RSS/sitemap/article extraction for public news.
3. Rendered browser extraction for JavaScript-heavy pages.
4. Authenticated browser extraction only when the user has legitimate access and the data cannot be obtained cleanly otherwise.

## What We Avoid

- Storing cookies or browser profiles in git.
- Depending on fragile visual coordinates.
- Making traffic look like something it is not.
- Ignoring robots, terms, cost, or rate limits.
- Treating an LLM summary as raw evidence.

## Output Contract

Every scraper should eventually return:

```json
{
  "source": "source-name",
  "fetched_at": "2026-05-18T00:00:00Z",
  "source_url": "https://example.com",
  "raw_artifact_path": "output/source/run/raw.json",
  "records": []
}
```

