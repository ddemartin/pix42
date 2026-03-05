"""SQLite connection management and schema initialisation."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Optional


_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS thumbnails (
    path        TEXT NOT NULL PRIMARY KEY,
    mtime       REAL NOT NULL,
    size        INTEGER NOT NULL,
    width       INTEGER NOT NULL,
    height      INTEGER NOT NULL,
    data        BLOB NOT NULL,
    created_at  REAL NOT NULL DEFAULT (unixepoch('now'))
);

CREATE TABLE IF NOT EXISTS metadata_cache (
    path        TEXT NOT NULL PRIMARY KEY,
    mtime       REAL NOT NULL,
    width       INTEGER,
    height      INTEGER,
    format_name TEXT,
    bit_depth   INTEGER,
    color_space TEXT,
    exif_json   TEXT,
    extra_json  TEXT,
    created_at  REAL NOT NULL DEFAULT (unixepoch('now'))
);

CREATE INDEX IF NOT EXISTS idx_thumbnails_mtime   ON thumbnails(mtime);
CREATE INDEX IF NOT EXISTS idx_metadata_mtime     ON metadata_cache(mtime);
"""


class Database:
    """
    Thread-safe SQLite wrapper.

    Each thread gets its own connection (check_same_thread=False +
    thread-local storage).
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._local   = threading.local()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # Initialise schema on main thread connection
        conn = self._get_connection()
        conn.executescript(_SCHEMA)
        conn.commit()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute a statement and return the cursor."""
        return self._get_connection().execute(sql, params)

    def executemany(self, sql: str, params_seq) -> sqlite3.Cursor:
        return self._get_connection().executemany(sql, params_seq)

    def commit(self) -> None:
        self._get_connection().commit()

    def close(self) -> None:
        conn: Optional[sqlite3.Connection] = getattr(self._local, "conn", None)
        if conn:
            conn.close()
            self._local.conn = None

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _get_connection(self) -> sqlite3.Connection:
        """Return a per-thread SQLite connection, creating it if needed."""
        conn: Optional[sqlite3.Connection] = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn
