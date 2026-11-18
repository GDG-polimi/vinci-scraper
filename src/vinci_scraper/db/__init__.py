"""SQLite storage: connection helper and schema migrations.

Migrations are plain SQL files in `migrations/`, named `NNNN_description.sql` and
applied in order. The number of the last applied migration is kept in SQLite's
`PRAGMA user_version`. To change the schema, add a new file. Never edit a
migration that is already on `main`.
"""

import re
import sqlite3
from importlib.resources import files
from pathlib import Path

_MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


def connect(path: str | Path) -> sqlite3.Connection:
    """Open the database, creating parent directories, with foreign keys enforced."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrations() -> list[tuple[int, str]]:
    """All bundled migrations as (number, sql), sorted by number."""
    found = []
    for entry in files(__package__).joinpath("migrations").iterdir():
        if match := _MIGRATION_NAME.match(entry.name):
            found.append((int(match.group(1)), entry.read_text(encoding="utf-8")))
    found.sort()
    numbers = [n for n, _ in found]
    if numbers != list(range(1, len(numbers) + 1)):
        raise RuntimeError(f"migrations must be numbered 0001, 0002, ... without gaps: {numbers}")
    return found


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def migrate(conn: sqlite3.Connection) -> list[int]:
    """Apply pending migrations, each in its own transaction. Returns the numbers applied."""
    current = schema_version(conn)
    applied = []
    for number, sql in migrations():
        if number <= current:
            continue
        # executescript() commits first, so wrap the script in an explicit transaction
        # to make each migration all-or-nothing.
        try:
            conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;")
        except sqlite3.Error:
            conn.rollback()
            raise
        applied.append(number)
    return applied
