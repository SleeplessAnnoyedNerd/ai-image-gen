from translations import get_strings


def test_english_has_required_keys():
    t = get_strings("en")
    for key in ["title", "generate_image", "generate_video", "prompt_label",
                "upload_label", "generating", "download", "error_generic",
                "lang_switch"]:
        assert key in t, f"Missing key: {key}"


def test_german_has_same_keys():
    en = get_strings("en")
    de = get_strings("de")
    assert set(en.keys()) == set(de.keys())


def test_unknown_lang_falls_back_to_english():
    t = get_strings("fr")
    assert t["title"] == get_strings("en")["title"]
