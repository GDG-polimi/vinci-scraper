import sqlite3

import pytest

from vinci_scraper import db
from vinci_scraper.cli import main

NOW = "2026-11-18T09:00:00Z"


@pytest.fixture
def conn():
    conn = db.connect(":memory:")
    db.migrate(conn)
    yield conn
    conn.close()


def add_document(conn, url="https://www.polimi.it/studenti", lang="it", doc_group=None):
    cur = conn.execute(
        "INSERT INTO documents (url, host, lang, doc_group, first_seen, last_seen)"
        " VALUES (?, 'www.polimi.it', ?, ?, ?, ?)",
        (url, lang, doc_group or url, NOW, NOW),
    )
    return cur.lastrowid


def test_migration_creates_the_four_tables(conn):
    tables = {
        row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert {"documents", "versions", "attachments", "fetch_log"} <= tables
    assert db.schema_version(conn) == len(db.migrations())


def test_migrate_is_idempotent(conn):
    assert db.migrate(conn) == []


def test_it_and_en_share_a_doc_group(conn):
    group = "https://www.polimi.it/studenti"
    add_document(conn, group, "it", group)
    add_document(conn, "https://www.polimi.it/en/students", "en", group)
    with pytest.raises(sqlite3.IntegrityError):
        add_document(conn, "https://www.polimi.it/en/students-2", "en", group)


def test_only_one_current_version_per_document(conn):
    doc = add_document(conn)
    insert = (
        "INSERT INTO versions (document_id, content_hash, text, fetched_at, is_current)"
        " VALUES (?, ?, 'text', ?, ?)"
    )
    conn.execute(insert, (doc, "hash-1", NOW, 0))
    conn.execute(insert, (doc, "hash-2", NOW, 1))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, (doc, "hash-3", NOW, 1))


def test_foreign_keys_are_enforced(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO versions (document_id, content_hash, text, fetched_at)"
            " VALUES (999, 'h', 't', ?)",
            (NOW,),
        )


def test_failed_migration_is_rolled_back(monkeypatch):
    conn = db.connect(":memory:")
    monkeypatch.setattr(
        db, "migrations", lambda: [(1, "CREATE TABLE ok (id INTEGER); SELECT * FROM missing;")]
    )
    with pytest.raises(sqlite3.OperationalError):
        db.migrate(conn)
    assert db.schema_version(conn) == 0
    assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'ok'").fetchone() is None


def test_cli_db_migrate(tmp_path, capsys):
    path = tmp_path / "nested" / "vinci.sqlite"
    assert main(["db", "migrate", "--db", str(path)]) == 0
    assert path.exists()
    assert "applied migrations: 1" in capsys.readouterr().out
    assert main(["db", "migrate", "--db", str(path)]) == 0
    assert "already up to date" in capsys.readouterr().out
