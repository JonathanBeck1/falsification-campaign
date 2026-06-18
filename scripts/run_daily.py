"""Daily trading-pipeline entrypoint.

Run once per US trading day, ~15 minutes after the close.

    python -m scripts.run_daily

Or via the installed console script:

    trader-daily run-once

For a long-running scheduler:

    trader-daily schedule
"""

from __future__ import annotations

from trader.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
