# Notes: LLM Model Choice for Enrichment + HybridBrain

Date: 2026-05-20
Status: provisional. Default stays Haiku 4.5 until we run an A/B comparison.
Owner: the maintainer (via Claude Code).

This is a note for Jonathan so the model-choice decision doesn't get lost.
We have two LLM-consuming layers — the event enricher (PR #24) and
HybridBrain (PRs #25/#26) — and right now both default to Claude Haiku 4.5
(`claude-haiku-4-5-20251001` in `src/trader/config.py:trader_llm_model`).
The question is whether that's the right call.

## Why Haiku 4.5 is the current default

- **Task profile matches small-model strength.** The work is narrow
  structured extraction: read ~500 tokens of news, output strict enums
  + quote-grounded claims. Validator catches hallucinations. The model
  is *not* picking direction, size, or timing — that's all rules.
- **Prompt caching wired (PR #16).** The ~1KB system prompt is cached at
  the `5m`/`1h` TTL set in `SystemContentBlock`. Cached input is
  ~$0.10/MTok on Haiku, vs $1/MTok uncached. The first call per cache
  window pays full price; the rest pay 1/10th. At our event volume
  (~50-150/day), most calls hit the cache.
- **Strong financial-domain priors.** Anthropic models train heavily on
  financial text and are reliable for sentiment labels and event tagging
  in this domain.
- **Reliable JSON mode.** With `response_format_json=True`, Haiku
  reliably emits parseable JSON. Adversarial headlines (prompt
  injection attempts) usually still produce valid JSON that the
  downstream validator rejects safely.
- **LiteLLM provider already configured.** `src/trader/llm/client.py`
  routes Anthropic via LiteLLM with no extra dependencies.

Estimated cost at current volume: **$0.15-$0.45/day actual, monthly $5-$15.**
The default `$1/day` cap (preventively enforced after PR #26) has ~3x
headroom even on a busy day.

## What's worth A/B testing

### Cheaper alternative: GPT-4o-mini / GPT-4.1-mini

- ~$0.15/MTok input, $0.60/MTok output → **5-7x cheaper than Haiku**
- Strong JSON mode via OpenAI's `response_format`
- OpenAI's automatic prompt caching applies on repeated system prompts
  (less granular than Anthropic's `cache_control` but free)
- LiteLLM routes OpenAI with no code change — just need
  `OPENAI_API_KEY` in `.env`

The risk: financial-domain calibration is empirically weaker on cheap
OpenAI models than on Haiku. We don't know by how much. **The A/B
harness exists to answer that question.**

### More expensive, NOT worth it for this job

- **Sonnet 4.6** (3x Haiku cost): marginal accuracy improvement on a
  narrow extraction task with a strict downstream validator. The
  validator already catches both models' mistakes equally. Save Sonnet
  for tasks where the LLM has discretion — which, by design in this
  codebase, it never does.
- **Opus 4.7** (15x Haiku cost): overkill. The architecture treats
  every LLM output as a *bucket suggestion*, not a decision. Paying
  Opus prices to suggest "high severity" instead of "medium" is silly.

### Don't use yet: cheap open-weight models

- DeepSeek, Qwen, Llama 3 8B-70B: JSON compliance drops on adversarial
  inputs; financial calibration weaker; limited prompt-caching support.
- Revisit in 6-12 months as these mature.

## The A/B harness

Spec lives in `brain/21_news_to_trade_thesis_algorithm.md` (see
"A/B harness spec" section). TL;DR of what to measure:

1. **Schema validation pass rate** (does the model emit parseable, valid
   EnrichmentV1?)
2. **Cost per event** (after caching, on a realistic 50-event sample)
3. **Sentiment label agreement** (does 4o-mini agree with Haiku ≥85%?)
4. **Severity bucket agreement** (≥80%?)
5. **End-to-end thesis agreement** — the one that matters most. If
   Haiku and 4o-mini produce labels that result in the *same Thesis
   record* from the THESIS_TABLE lookup, the cheaper model is good
   enough. If they diverge, label quality actually impacts trades and
   we keep Haiku.

### Switch threshold

Switch to the cheaper model only if **all five** thresholds pass. A
partial win (e.g., cost wins but thesis agreement is 70%) is not a
switch — that means the cheaper model is producing labels that change
trading behavior, which is the thing we explicitly want to avoid.

### Build order

A/B harness needs PR #24's enricher infrastructure (EnrichmentV1
schema, prompts, sanitizer, validator). Wait for PR #24 to merge before
building the harness. Once it merges:

1. Add `OPENAI_API_KEY` to `.env`
2. Build the CLI: `trader-daily compare-enrichment-models ...`
3. Run on the demo corpus first (no real spend, deterministic mock
   output), then on a real 50-event sample
4. Write the result as a decision doc in `brain/decisions/`

## Open question for Jonathan

Do you want per-job model selection long-term? i.e., enricher on Haiku
(financial nuance matters more), HybridBrain on 4o-mini (just a
bucket-picker the policy translates)? That's two LiteLLM keys to manage,
which is fine, but it's worth deciding upfront whether the cost
savings of per-job choice justify the complexity.

My lean: keep one model for both until the A/B says otherwise. If A/B
shows 4o-mini is fine for HybridBrain but not for enrichment, then
split. Don't split preemptively.

## Where this lives in code

- Default model: `src/trader/config.py:trader_llm_model`
- LLMClient that consumes it: `src/trader/llm/client.py`
- Cache-control wiring: `src/trader/llm/client.py:SystemContentBlock`
- Enricher that uses it: `src/trader/enrichment/service.py` (after #24)
- HybridBrain that uses it: `src/trader/signals/hybrid.py`

Changing the default is a one-line edit in config.py. The whole
codebase routes through `LLMClient.complete()`, which routes through
LiteLLM, which dispatches to the configured provider. There's no
hard-coded provider name anywhere downstream.
