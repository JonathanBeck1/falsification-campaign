"""Baseline marker for databases already matching schema.sql."""

from __future__ import annotations

import sqlite3


def run(conn: sqlite3.Connection) -> None:
    """No-op: schema.sql creates the baseline tables before migrations run."""
    return None
