"""Database engine, session factory, schema init, and FTS5 trigger setup.

WAL mode + 5s busy-timeout makes concurrent writes from the host-side backup
script and the in-container app safe. FTS5 uses content_rowid='id' over
entries.body_text and is kept in sync via standard FTS5 triggers.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

from driftnote.models import Base

_SESSION_FACTORIES: dict[int, sessionmaker[Session]] = {}

_FTS_DDL = """
CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    body_text,
    content='entries',
    content_rowid='id'
);
"""

_FTS_TRIGGERS = [
    """
    CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
        INSERT INTO entries_fts(rowid, body_text) VALUES (new.id, new.body_text);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS entries_ad AFTER DELETE ON entries BEGIN
        INSERT INTO entries_fts(entries_fts, rowid, body_text) VALUES('delete', old.id, old.body_text);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS entries_au AFTER UPDATE ON entries BEGIN
        INSERT INTO entries_fts(entries_fts, rowid, body_text) VALUES('delete', old.id, old.body_text);
        INSERT INTO entries_fts(rowid, body_text) VALUES (new.id, new.body_text);
    END;
    """,
]


def make_engine(db_path: Path) -> Engine:
    """Create an Engine for the given file. WAL + foreign keys enabled per-connection."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"timeout": 5.0},  # busy-timeout in seconds
    )

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection: object, _record: object) -> None:
        cur = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    _SESSION_FACTORIES[id(engine)] = sessionmaker(engine, expire_on_commit=False)
    return engine


def init_db(engine: Engine) -> None:
    """Apply ORM schema, create FTS5 virtual table + triggers. Idempotent."""
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text(_FTS_DDL))
        for ddl in _FTS_TRIGGERS:
            conn.execute(text(ddl))


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Context manager that yields a Session, commits on success, rolls back on error."""
    factory: sessionmaker[Session] = _SESSION_FACTORIES[id(engine)]
    session = factory()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
