import sqlite3

from services import prompt_store


def test_add_then_recent_returns_prompt():
    prompt_store.add("a sunset over water")
    assert [r.text for r in prompt_store.recent()] == ["a sunset over water"]


def test_readd_moves_to_front_without_duplicating():
    prompt_store.add("first")
    prompt_store.add("second")
    prompt_store.add("first")
    assert [r.text for r in prompt_store.recent()] == ["first", "second"]


def test_recent_is_newest_first_and_capped():
    for i in range(30):
        prompt_store.add(f"prompt {i}")
    result = prompt_store.recent(25)
    assert len(result) == 25
    assert result[0].text == "prompt 29"
    assert result[-1].text == "prompt 5"


def test_blank_prompts_are_ignored():
    prompt_store.add("")
    prompt_store.add("   ")
    assert prompt_store.recent() == []


def test_prompt_is_stripped_before_storing():
    prompt_store.add("  padded  ")
    assert [r.text for r in prompt_store.recent()] == ["padded"]


def test_long_prompt_is_truncated():
    prompt_store.add("x" * 5000)
    assert len(prompt_store.recent()[0].text) == prompt_store._MAX_LEN


def test_recent_on_empty_db_returns_empty_list():
    assert prompt_store.recent() == []


def test_legacy_two_column_db_gains_use_count_and_keeps_rows():
    """The live prompts.db predates use_count. CREATE TABLE IF NOT EXISTS is a
    no-op against it, so an explicit ALTER is the only thing that migrates it."""
    conn = sqlite3.connect(prompt_store._DB_PATH)
    conn.execute(
        "CREATE TABLE prompts (text TEXT PRIMARY KEY, used_at REAL NOT NULL)"
    )
    conn.execute("INSERT INTO prompts VALUES ('an old prompt', 1000.0)")
    conn.commit()
    conn.close()

    rows = prompt_store.recent()

    assert [row.text for row in rows] == ["an old prompt"]
    assert rows[0].use_count == 1


def test_readd_increments_use_count():
    prompt_store.add("a repeated prompt")
    prompt_store.add("a repeated prompt")
    prompt_store.add("a repeated prompt")

    rows = prompt_store.recent()

    assert len(rows) == 1
    assert rows[0].use_count == 3


def test_recent_honours_min_count():
    prompt_store.add("used once")
    prompt_store.add("used twice")
    prompt_store.add("used twice")

    assert [row.text for row in prompt_store.recent(min_count=2)] == ["used twice"]


def test_top_returns_most_used_first():
    prompt_store.add("rare")
    for _ in range(3):
        prompt_store.add("common")
    for _ in range(2):
        prompt_store.add("middling")

    assert [row.text for row in prompt_store.top(2)] == ["common", "middling"]


def test_top_is_empty_when_nothing_has_been_reused():
    """A table of all-ones has no favourites. Showing three arbitrary rows
    under a 'favourites' heading would be a lie."""
    prompt_store.add("one")
    prompt_store.add("two")

    assert prompt_store.top() == []
