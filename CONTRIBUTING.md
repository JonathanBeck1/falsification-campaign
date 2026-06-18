# Contributing

This project should move quickly without becoming chaotic. The operating model is branch-first collaboration with durable notes in `brain/`.

## Branch Workflow

1. Fetch the latest remote state.

   ```bash
   git fetch origin --prune
   ```

2. Inspect the branch you want to build from.

   ```bash
   git log --oneline --graph --decorate --all -20
   git diff origin/main...origin/<branch-name>
   ```

3. Create your own branch.

   ```bash
   git switch -c codex/<short-task-name> origin/main
   ```

   or:

   ```bash
   git switch -c claude/<short-task-name> origin/main
   ```

4. Push your branch.

   ```bash
   git push -u origin <your-branch-name>
   ```

5. Open a PR. Merge through GitHub after review.

## Branch Naming

- `main`: stable integration branch
- `codex/*`: Codex-owned work
- `claude/*`: Claude Code-owned work
- `proposal/*`: larger proposals and architecture branches
- `feature/*`: accepted features
- `research/*`: experiments and repo/vendor research
- `fix/*`: narrow bug fixes

Do not push to a collaborator's branch unless the branch owner explicitly asks you to do that.

## Reading Each Other's Work

Reading branches is encouraged. Use:

```bash
git fetch origin --prune
git log --oneline --graph --decorate --all -30
git diff origin/main...origin/<branch-name>
```

To build on someone else's work, branch from it:

```bash
git switch -c codex/<followup-task> origin/claude/<their-branch>
```

or:

```bash
git switch -c claude/<followup-task> origin/codex/<their-branch>
```

Then open a PR back into the parent branch or into `main`, depending on the state of the work.

## PR Checklist

Every PR should include:

- what changed
- parent branch
- intended merge target
- verification commands
- data/source assumptions
- new secrets or environment variables, if any
- follow-up work

## Protected Materials

Never commit:

- `.env`
- `.venv/`
- API keys
- cookies
- browser profiles
- raw scrape dumps
- account screenshots
- paid data exports
- large generated artifacts

Local generated data belongs under `output/` unless promoted into curated fixtures.
