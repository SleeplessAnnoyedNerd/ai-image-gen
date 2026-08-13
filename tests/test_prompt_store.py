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


def test_top_respects_min_count():
    """top() must agree with recent() on what 'hidden' means: a prompt below
    the cutoff must not appear in either block."""
    for _ in range(2):
        prompt_store.add("used twice")
    for _ in range(5):
        prompt_store.add("used five times")

    assert [r.text for r in prompt_store.top(3, min_count=3)] == ["used five times"]


def test_keyword_search_is_order_independent():
    prompt_store.add("a red bikini on a beach")
    prompt_store.add("a blue dress in a field")

    for query in ("red bikini", "bikini red"):
        rows, regex_error, total = prompt_store.search(query)
        assert [r.text for r in rows] == ["a red bikini on a beach"]
        assert regex_error is False
        assert total == 1


def test_keyword_search_is_case_insensitive_including_umlauts():
    """The specific reason matching is not done in SQL: SQLite's LIKE and
    lower() are ASCII-only, so 'Größe' would not be found by 'größe'."""
    prompt_store.add("Die Größe des Bildes")

    rows, _, _ = prompt_store.search("größe")

    assert [r.text for r in rows] == ["Die Größe des Bildes"]


def test_sql_wildcards_in_a_query_are_literal():
    """The other reason: with LIKE, '%' and '_' would match anything."""
    prompt_store.add("50% off everything")
    prompt_store.add("nothing relevant here")

    rows, _, _ = prompt_store.search("%")

    assert [r.text for r in rows] == ["50% off everything"]


def test_slash_delimited_query_is_a_regex():
    prompt_store.add("a bathing suit")
    prompt_store.add("a winter coat")

    rows, regex_error, _ = prompt_store.search("/bikini|bathing/")

    assert [r.text for r in rows] == ["a bathing suit"]
    assert regex_error is False


def test_invalid_regex_reports_an_error_instead_of_raising():
    prompt_store.add("anything")

    rows, regex_error, total = prompt_store.search("/foo(/")

    assert rows == []
    assert regex_error is True
    assert total == 0


def test_half_typed_slash_is_a_keyword_not_a_broken_regex():
    """Typing '/foo' on the way to '/foo/' must not flash an error."""
    prompt_store.add("the /foo directory")
    prompt_store.add("unrelated")

    for query in ("/foo", "//"):
        rows, regex_error, _ = prompt_store.search(query)
        assert regex_error is False, f"{query!r} should be a keyword"

    rows, _, _ = prompt_store.search("/foo")
    assert [r.text for r in rows] == ["the /foo directory"]


def test_empty_query_matches_nothing_rather_than_everything():
    """all([]) is True, so a missing guard would return the whole table."""
    prompt_store.add("something")

    assert prompt_store.search("") == ([], False, 0)
    assert prompt_store.search("   ") == ([], False, 0)


def test_search_ignores_min_use_count():
    """A prompt used once is exactly what search exists to find."""
    prompt_store.add("used exactly once")

    rows, _, _ = prompt_store.search("exactly")

    assert [r.text for r in rows] == ["used exactly once"]


def test_search_caps_rows_but_reports_the_true_total():
    for i in range(10):
        prompt_store.add(f"candidate number {i}")

    rows, _, total = prompt_store.search("candidate", limit=3)

    assert len(rows) == 3
    assert total == 10


def test_snippet_is_centred_on_a_late_match():
    text = ("x" * 800) + "NEEDLE" + ("y" * 200)
    prompt_store.add(text)

    rows, _, _ = prompt_store.search("needle")
    segments = rows[0].segments

    assert ("NEEDLE", True) in segments
    assert segments[0] == ("…", False), "text before the window must be elided"
    assert segments[-1] == ("…", False), "text after the window must be elided"

    body = "".join(chunk for chunk, _ in segments if (chunk != "…"))
    assert body == text[(800 - 60):(806 + 140)]


def test_every_match_in_the_window_is_marked_not_just_the_first():
    prompt_store.add("cat and cat and cat")

    rows, _, _ = prompt_store.search("cat")

    assert [chunk for chunk, is_match in rows[0].segments if (is_match)] == ["cat"] * 3


def test_anchored_regex_still_produces_highlighting():
    """Regression guard: spans must come from the full text, not the window.
    A window cut short of the end does not satisfy '$', so computing spans on
    the slice would match the row and then highlight nothing."""
    text = ("x" * 900) + " the end"
    prompt_store.add(text)

    rows, _, _ = prompt_store.search("/end$/")

    assert len(rows) == 1
    assert any(is_match for _, is_match in rows[0].segments), (
        "row matched but nothing was highlighted"
    )


def test_a_pattern_that_can_match_empty_produces_no_empty_marks():
    prompt_store.add("aaa bbb")

    rows, _, _ = prompt_store.search("/a*/")

    assert all((chunk != "") for chunk, _ in rows[0].segments)


def test_overlapping_terms_never_duplicate_text():
    prompt_store.add("a lighthouse at dusk")

    rows, _, _ = prompt_store.search("lighthouse light house")

    body = "".join(chunk for chunk, _ in rows[0].segments if (chunk != "…"))
    assert body == "a lighthouse at dusk"
