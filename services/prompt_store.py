import re
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


def _compile(query: str) -> tuple[list | None, bool]:
    """Turn a query into a list of patterns that must ALL match.

    Both modes compile to the same thing on purpose: the patterns are used
    for filtering AND for locating spans to highlight, so a single mechanism
    is the only way the two can never disagree. The obvious keyword shortcut
    -- `term in text.lower()` -- would disagree, because lowering can change
    length (`"İ".lower()` is two code points) and the offsets no longer map
    back onto the original text.

    Returns (patterns, regex_error). patterns is None when there is nothing
    to search for.
    """
    q = query.strip()
    if (not q):
        return (None, False)
    # Regex mode needs BOTH delimiters and a non-empty body. A half-typed
    # "/foo" is a keyword, so typing towards "/foo/" never flashes an error,
    # and "//" is a literal rather than an empty pattern matching everything.
    if ((len(q) >= 3) and q.startswith("/") and q.endswith("/")):
        try:
            return ([re.compile(q[1:-1], re.IGNORECASE)], False)
        except re.error:
            return (None, True)
    # re.escape keeps % and _ literal for free, and re.IGNORECASE is
    # Unicode-aware, so "größe" finds "Größe".
    return ([re.compile(re.escape(term), re.IGNORECASE) for term in q.split()], False)


def _segments(text: str, patterns: list) -> list[tuple[str, bool]]:
    """Split a snippet of text into (chunk, is_match) pairs.

    Spans are found over the FULL text, never over the window: '$' and
    lookbehind do not survive slicing, so a window-local search would match
    the row and then highlight nothing.
    """
    spans = []
    for rx in patterns:
        for match in rx.finditer(text):
            # Zero-length matches (/a*/, /^/) would render as empty <mark>s.
            if (match.end() > match.start()):
                spans.append((match.start(), match.end()))
    spans.sort()

    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if (merged and (start <= merged[-1][1])):
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    if (merged):
        window_start = max(0, (merged[0][0] - _SNIPPET_BEFORE))
        window_end = min(len(text), (merged[0][1] + _SNIPPET_AFTER))
    else:
        window_start = 0
        window_end = min(len(text), (_SNIPPET_BEFORE + _SNIPPET_AFTER))

    out: list[tuple[str, bool]] = []
    if (window_start > 0):
        out.append(("…", False))

    cursor = window_start
    for start, end in merged:
        start = max(start, window_start)
        end = min(end, window_end)
        if (start >= end):
            continue
        if (start > cursor):
            out.append((text[cursor:start], False))
        out.append((text[start:end], True))
        cursor = end
    if (cursor < window_end):
        out.append((text[cursor:window_end], False))

    if (window_end < len(text)):
        out.append(("…", False))
    return out


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


def top(n: int = 3, min_count: int = 1) -> list[Row]:
    """The n most-used prompts, for pinning above the recent list.

    The cutoff is max(2, min_count): the floor of 2 keeps a never-reused
    table from producing three arbitrary 'favourites', and the min_count
    floor keeps pinned rows consistent with what recent() hides.
    """
    cutoff = max(2, min_count)
    with _db() as conn:
        rows = conn.execute(
            "SELECT text, use_count FROM prompts "
            "WHERE use_count >= ? ORDER BY use_count DESC, used_at DESC LIMIT ?",
            (cutoff, n),
        ).fetchall()
    return [Row(text, use_count, _segments(text, [])) for text, use_count in rows]


def search(query: str, limit: int = 50) -> tuple[list[Row], bool, int]:
    """Prompts matching query, newest first.

    Returns (rows, regex_error, total). total counts every match, not just
    the ones returned, so the caller can say "showing 50 of 130" -- which is
    why the scan does not stop early at limit.

    Deliberately has no min_count parameter: search sees every prompt.

    Accepted risk: `re` cannot be interrupted, so a valid but catastrophic
    pattern like /(a+)+$/ can spin. Single-user tool on a trusted LAN; the
    only person who can type it is the one it would inconvenience.
    """
    patterns, regex_error = _compile(query)
    if (patterns is None):
        return ([], regex_error, 0)

    with _db() as conn:
        rows = conn.execute(
            "SELECT text, use_count FROM prompts ORDER BY used_at DESC"
        ).fetchall()

    out = []
    total = 0
    for text, use_count in rows:
        if (not all((rx.search(text)) for rx in patterns)):
            continue
        total += 1
        if (len(out) < limit):
            out.append(Row(text, use_count, _segments(text, patterns)))
    return (out, False, total)
