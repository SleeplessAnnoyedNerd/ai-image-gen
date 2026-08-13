import sqlite3
import threading
from contextlib import contextmanager
from time import time
from typing import NamedTuple

_DB_PATH = "prompts.db"
_MAX_LEN = 2000
_lock = threading.Lock()


class Row(NamedTuple):
    """One prompt as the templates want it.

    `segments` is the snippet split into (chunk, is_match) pairs. The template
    wraps the matching chunks in <mark> and Jinja autoescapes every chunk, so
    no user text ever needs |safe.
    """
    text: str
    use_count: int
    segments: list[tuple[str, bool]]


@contextmanager
def _db():
    """Connect-per-call. Sidesteps sqlite3's thread-affinity rule entirely.

    CREATE TABLE IF NOT EXISTS covers a fresh database; it is a no-op against
    an existing one, so a schema change needs its own guarded ALTER below.
    The PRAGMA is an in-memory schema read, cheap enough to run per call.
    """
    with _lock:
        conn = sqlite3.connect(_DB_PATH)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS prompts ("
                "  text TEXT PRIMARY KEY,"
                "  used_at REAL NOT NULL,"
                "  use_count INTEGER NOT NULL DEFAULT 1"
                ")"
            )
            cols = {row[1] for row in conn.execute("PRAGMA table_info(prompts)")}
            if ("use_count" not in cols):
                conn.execute(
                    "ALTER TABLE prompts ADD COLUMN use_count INTEGER NOT NULL DEFAULT 1"
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
            "INSERT INTO prompts (text, used_at, use_count) VALUES (?, ?, 1) "
            "ON CONFLICT(text) DO UPDATE SET "
            "  used_at   = excluded.used_at,"
            "  use_count = use_count + 1",
            (text, time()),
        )


_SNIPPET_BEFORE = 60
_SNIPPET_AFTER = 140


def _segments(text: str, patterns: list) -> list[tuple[str, bool]]:
    """Split text into (chunk, is_match) pairs for the template to render."""
    return [(text[:(_SNIPPET_BEFORE + _SNIPPET_AFTER)], False)]


def recent(n: int = 25, min_count: int = 1) -> list[Row]:
    """The n most recently used prompts, newest first.

    min_count trims the default list only; search deliberately ignores it,
    because the prompt you search for is usually the one you used once.
    """
    with _db() as conn:
        rows = conn.execute(
            "SELECT text, use_count FROM prompts "
            "WHERE use_count >= ? ORDER BY used_at DESC LIMIT ?",
            (min_count, n),
        ).fetchall()
    return [Row(text, use_count, _segments(text, [])) for text, use_count in rows]


def top(n: int = 3) -> list[Row]:
    """The n most-used prompts, for pinning above the recent list.

    use_count > 1 keeps a never-reused table from producing three arbitrary
    'favourites'.
    """
    with _db() as conn:
        rows = conn.execute(
            "SELECT text, use_count FROM prompts "
            "WHERE use_count > 1 ORDER BY use_count DESC, used_at DESC LIMIT ?",
            (n,),
        ).fetchall()
    return [Row(text, use_count, _segments(text, [])) for text, use_count in rows]
