# News Event Schema

## Purpose

The event schema is the bridge between messy source data and testable trading signals.

Raw article text is not a signal. A normalized event may become one.

## Draft Event Record

```json
{
  "event_id": "evt_...",
  "source": "businessinsider",
  "source_url": "https://example.com/article",
  "published_at": "2026-05-18T13:45:00Z",
  "observed_at": "2026-05-18T13:45:12Z",
  "title": "Article title",
  "entities": [
    {
      "name": "Apple Inc.",
      "ticker": "AAPL",
      "confidence": 0.96,
      "role": "primary"
    }
  ],
  "asset_scope": ["single_name", "index"],
  "index_exposure": ["SPY", "QQQ"],
  "event_type": "earnings_guidance",
  "sentiment": "negative",
  "sentiment_score": -0.71,
  "urgency": "high",
  "novelty_score": 0.64,
  "source_credibility": 0.82,
  "summary": "Short factual summary.",
  "evidence": [
    {
      "text": "Short source excerpt or pointer.",
      "location": "paragraph:3"
    }
  ],
  "model_outputs": {
    "classifier": "finbert-or-llm-name",
    "version": "v0"
  }
}
```

## Required Timestamps

- `published_at`: when the source says it was published
- `observed_at`: when our system saw it
- `ingested_at`: when it entered storage
- `classified_at`: when the event model processed it

Latency matters. A great event seen too late may have no trading value.

## First Event Types

- earnings surprise
- guidance raise/lower
- M&A
- regulatory action
- lawsuit/investigation
- product launch/failure
- macro surprise
- Fed/rate commentary
- geopolitical shock
- analyst upgrade/downgrade
- unusual social velocity

