import sqlite3
import threading
from contextlib import contextmanager
from time import time

_DB_PATH = "prompts.db"
_MAX_LEN = 2000
_lock = threading.Lock()


@contextmanager
def _db():
    """Connect-per-call. Sidesteps sqlite3's thread-affinity rule entirely,
    and makes CREATE TABLE IF NOT EXISTS the only init step there is."""
    with _lock:
        conn = sqlite3.connect(_DB_PATH)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS prompts ("
                "  text TEXT PRIMARY KEY,"
                "  used_at REAL NOT NULL"
                ")"
            )
            yield conn
            conn.commit()
        finally:
            # sqlite3's own context manager commits but does not close.
            conn.close()


def add(text: str) -> None:
    """Record a prompt, bumping it to the front if already present."""
    # Truncate at the trust boundary: the app binds 0.0.0.0 and the textarea
    # is unbounded, so without a cap one POST loop fills the disk.
    text = text.strip()[:_MAX_LEN]
    if (not text):
        return
    with _db() as conn:
        conn.execute(
            "INSERT INTO prompts (text, used_at) VALUES (?, ?) "
            "ON CONFLICT(text) DO UPDATE SET used_at = excluded.used_at",
            (text, time()),
        )


def recent(n: int = 25) -> list[str]:
    """The n most recently used prompts, newest first."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT text FROM prompts ORDER BY used_at DESC LIMIT ?", (n,)
        ).fetchall()
    return [row[0] for row in rows]
