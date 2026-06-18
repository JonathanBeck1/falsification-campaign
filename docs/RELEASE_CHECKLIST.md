# Pre-Publish Checklist — open-source release

State of the `claude/catalyst-edge` branch for a public release. Generated from a
multi-agent release audit (secrets / licensed-data / PII / portability) + a
per-test numerical-integrity audit. **Nothing has been published, pushed, or made
public** — that is your call. The audit's working artifacts are under
`docs/oss-release/` (`RELEASE_READINESS.md`, `INTEGRITY_REPORT.md`, the safety
JSON, and the source drafts).

---

## ✅ DONE (committed on `claude/catalyst-edge`)

- **Secrets:** full 273-commit history scanned — **zero credential leaks**. No
  history scrubbing required for secrets.
- **Licensed data un-tracked** (`git rm --cached`, local copies kept; `output/`
  is git-ignored so they stay out): `output/thetadata_depth_probe.json` (raw
  ThetaData quotes), `output/cef/cef_tiingo_symbols.parquet`, `cef_universe.parquet`
  (Tiingo catalogue).
- **PII scrubbed at HEAD:** personal emails → `you@example.com`; contributor names
  → role labels; GitHub handles → `<your-handle>`; hardware/budget specifics
  generalized. **Zero `/Users/<real-name>` paths** remain in tracked files.
- **Portability:** lake paths resolve from `TRADER_EOD_LAKE_ROOT` /
  `TRADER_LAKE_ROOT` (repo-relative defaults) instead of hardcoded absolutes.
- **LICENSE** added (MIT for code + scope note). **Public README** installed
  (campaign-led; old internal README preserved at `docs/repo-internal-readme.md`).
- **DATA.md** (`docs/DATA.md`) + **REPRODUCE.md** (`docs/REPRODUCE.md`) authored.
- **Paper integrity:** reconciled `PAPER_DRAFT.md` to the live runs (T25 self
  -contradiction removed; T29 re-synced; T01 SPY/plumbing relabel); scoreboard
  regenerated. Added **§7.6 threats-to-validity** + companion
  `research/THREATS_TO_VALIDITY.md` (§9) and `research/RELATED_WORK.md` (§10).
- **Verification:** 1,813 financial tests pass; `ruff` clean on all touched code.

## ⚠️ YOUR DECISIONS before pushing (cannot be made for you)

1. **Set the copyright holder** in `LICENSE` (currently `[SET COPYRIGHT HOLDER]`).
2. **Git history still carries the old names/emails/paths.** HEAD is clean, but if
   you want a clean *history*, run a one-time scrub (decision W8):
   ```bash
   # OPTIONAL — rewrites history; coordinate if anyone else has clones
   git filter-repo --mailmap mailmap.txt     # map old author emails → noreply
   ```
   Otherwise accept it (normal for many OSS repos).
3. **Tiingo regeneration (optional):** the CEF code can rebuild its universe from
   the free SEC path so it works without the un-tracked Tiingo parquets:
   ```bash
   .venv/bin/python scripts/build_cef_universe.py --source sec
   ```
4. **Verify `[verify]` citations** in `research/RELATED_WORK.md` (7 markers) against
   the primary sources before formal/academic publication.
5. **Decide what ships:** `brain/` (candid planning, now PII-redacted) and
   `research/trading-repos/` (a scraped competitor-repo dossier — consider
   excluding) are kept by default; remove if you'd rather they stay private.
6. **Publish** — create the public repo / push. (Claude will not push or change
   repo visibility.)

## 🔁 Final smoke test (run on a clean checkout before publishing)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
python -m pytest tests/financial/ -q          # expect ~1,813 passed
python scripts/build_campaign_scoreboard.py    # regenerates the scoreboard
git grep -n "/Users/" -- ':!.env*' ':!docs/oss-release/'   # expect: only the .env.example placeholder
```

## 📋 Deeper (non-blocking) paper-hardening backlog

The adversarial review produced a prioritized edit list in
`docs/oss-release/PAPER_FIXES.md` (17 items). The publication-blocking ones (number
reconciliation, §7.3 table, the claim-vs-conjecture scope, multiple-testing/power
defense) are **done**. The remaining P1/P2 items (reclassify T24 out of
friction-scale; per-cluster cost table; the T13/T32 two-stage gate-pass framing;
the q≠0 robustness re-run) tighten the paper further but change no verdict.
