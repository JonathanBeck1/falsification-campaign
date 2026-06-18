# Collaboration Protocol

## Repo Hygiene

Never commit:

- `.venv/`
- `.env`
- API keys
- cookies
- Chrome profiles
- raw local scrape outputs
- large generated artifacts
- private account screenshots

## Branching

The current branch ownership workflow is documented in `brain/12_branch_collaboration_workflow.md`, `AGENTS.md`, `CLAUDE.md`, and `CONTRIBUTING.md`.

Recommended branch names:

```text
feature/source-adapter-name
feature/alpaca-paper-orders
research/news-event-schema
```

## Pull Request Standard

Each PR should explain:

- what changed
- why it changed
- how it was tested
- what data/source assumptions it makes
- what follow-up remains

## Docs Standard

When a decision matters later, write it down in `brain/decisions/`.

Decision files should include:

- date
- context
- decision
- consequences
- owner if relevant

## Development Standard

- Keep adapters small and source-specific.
- Keep normalization deterministic where possible.
- Add tests around parsing and schema conversion.
- Store raw evidence paths in outputs.
- Prefer boring, auditable code over clever pipelines.

## Working Agreement

This project will move fast, but it should not become chaotic. The `brain/` folder exists so the maintainer can re-enter the project quickly and understand what is true, what is planned, and what is still uncertain.
