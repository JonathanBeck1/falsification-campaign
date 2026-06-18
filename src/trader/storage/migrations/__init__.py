"""Minimal SQLite schema migrations using PRAGMA user_version."""

from __future__ import annotations

import importlib
import pkgutil
import re
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from types import ModuleType

_MIGRATION_RE = re.compile(r"^m(?P<version>\d{4})_[a-z0-9_]+$")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    run: Callable[[sqlite3.Connection], None]


def _load_migration(module_name: str) -> Migration | None:
    match = _MIGRATION_RE.match(module_name)
    if match is None:
        return None

    module: ModuleType = importlib.import_module(f"{__name__}.{module_name}")
    run = getattr(module, "run", None)
    if not callable(run):
        raise TypeError(f"Migration {module_name} must define run(conn)")

    return Migration(version=int(match.group("version")), name=module_name, run=run)


def available_migrations() -> list[Migration]:
    """Return bundled migrations sorted by version."""
    migrations = [
        migration
        for module_info in pkgutil.iter_modules(__path__)
        if (migration := _load_migration(module_info.name)) is not None
    ]
    return sorted(migrations, key=lambda migration: migration.version)


def latest_version(migrations: Iterable[Migration] | None = None) -> int:
    """Return the highest known migration version."""
    selected = available_migrations() if migrations is None else migrations
    versions = [migration.version for migration in selected]
    return max(versions, default=0)


def get_user_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0])


def run_migrations(conn: sqlite3.Connection, migrations: Iterable[Migration] | None = None) -> None:
    """Apply pending migrations, recording progress in PRAGMA user_version."""
    current_version = get_user_version(conn)
    selected = available_migrations() if migrations is None else migrations
    ordered = sorted(selected, key=lambda migration: migration.version)

    for migration in ordered:
        if migration.version <= current_version:
            continue

        conn.execute("BEGIN")
        try:
            migration.run(conn)
            conn.execute(f"PRAGMA user_version = {migration.version}")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")
            current_version = migration.version
