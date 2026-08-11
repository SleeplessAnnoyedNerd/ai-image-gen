from services import prompt_store


def test_add_then_recent_returns_prompt():
    prompt_store.add("a sunset over water")
    assert prompt_store.recent() == ["a sunset over water"]


def test_readd_moves_to_front_without_duplicating():
    prompt_store.add("first")
    prompt_store.add("second")
    prompt_store.add("first")
    assert prompt_store.recent() == ["first", "second"]


def test_recent_is_newest_first_and_capped():
    for i in range(30):
        prompt_store.add(f"prompt {i}")
    result = prompt_store.recent(25)
    assert len(result) == 25
    assert result[0] == "prompt 29"
    assert result[-1] == "prompt 5"


def test_blank_prompts_are_ignored():
    prompt_store.add("")
    prompt_store.add("   ")
    assert prompt_store.recent() == []


def test_prompt_is_stripped_before_storing():
    prompt_store.add("  padded  ")
    assert prompt_store.recent() == ["padded"]


def test_long_prompt_is_truncated():
    prompt_store.add("x" * 5000)
    stored = prompt_store.recent()[0]
    assert len(stored) == prompt_store._MAX_LEN


def test_recent_on_empty_db_returns_empty_list():
    assert prompt_store.recent() == []
