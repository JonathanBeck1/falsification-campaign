# LLM Agent Boundaries

## Role

LLMs are useful analysts. They are not the trading engine.

Good LLM jobs:

- summarize articles
- classify event types
- explain why a source may matter
- identify possible tickers/entities
- compare conflicting evidence
- produce structured JSON for review
- write analyst reports

Bad LLM jobs:

- place trades directly
- override risk gates
- invent missing data
- trade from vibes
- make decisions without stored evidence

## Required Controls

Every LLM output used downstream should store:

- model name
- prompt version
- input evidence IDs
- raw model output
- parsed structured output
- validation status
- timestamp

## TradingAgents And Similar Repos

Repos like TradingAgents, FinGPT, ai-hedge-fund, and openbb-agents are useful for inspiration.

They should influence:

- analyst role design
- debate/checklist patterns
- report generation
- research workflows

They should not become the production trading core without serious review.

## First LLM Milestone

Classify stored news articles into strict event JSON, then compare the model output against a manually reviewed sample. Do not connect this to orders until the labeling quality is known.

