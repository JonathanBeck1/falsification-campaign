# Provenance

This repository was published as a single snapshot on 2026-06-17. Its commit history does not show the order in which files were written.

What that means for the pre-registration claim: every test has a `research/*_preregistration.md`, and every test that reached a verdict has a `research/*_decision.md`. I wrote each pre-registration before running the test it describes. This repository cannot prove that. The working history that would show it was not preserved in git, and the pre-registration and decision files carry no internal dates.

What is checkable here:

- `brain/34_master_test_registry.md` is dated 2026-06-14, three days before the snapshot.
- The gate (`src/trader/research/gate.py`) takes a pre-registration acknowledgement flag that defaults to `False`. A test run without it fails the gate rather than passing. The test suite exercises this.
- Every verdict's arithmetic can be re-derived from the committed derived artifacts and the registry.

If you are evaluating this work for research integrity, treat the pre-registration ordering as an author assertion, not a demonstrated fact. The later study in this line, [llm-calibration-eval](https://github.com/JonathanBeck1/llm-calibration-eval), commits hypotheses, decision rules, and the prompt to git before any data is collected, so its history does show the ordering.
