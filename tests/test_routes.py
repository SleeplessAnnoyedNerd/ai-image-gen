import io
import base64
from unittest.mock import patch, MagicMock
from werkzeug.datastructures import MultiDict
from services import job_store


def setup_function():
    job_store._jobs.clear()


def test_index_returns_200(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Generator" in resp.data


def test_lang_switch(client):
    resp = client.post("/lang", data={"lang": "de"}, follow_redirects=True)
    assert resp.status_code == 200
    assert "KI-Bild" in resp.data.decode("utf-8")


def test_lang_redirects_back_to_extend(client):
    resp = client.post("/lang", data={"lang": "en", "next": "/extend"})
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/extend"


def test_lang_rejects_malicious_next(client):
    for bad in ("https://evil.com", "//evil.com", "/prompts", "/../etc"):
        resp = client.post("/lang", data={"lang": "en", "next": bad})
        assert resp.status_code == 302
        assert resp.headers["Location"] == "/"


def test_generate_image_job_starts(client):
    with patch("app.image_gen.generate_image", return_value=b"png-bytes"), \
         patch("app.threading.Thread") as mock_thread:
        # Run the job body inline: a real daemon thread can outlive the test
        # and write to .cache/ after the cwd fixture has unwound.
        mock_thread.side_effect = lambda target, args, daemon: \
            type("T", (), {"start": lambda self: target(*args)})()
        resp = client.post("/generate", data={
            "output_type": "image",
            "prompt": "a sunset",
        })
    assert resp.status_code == 200
    assert b"job_id" in resp.data or b"generating" in resp.data.lower()


def test_generate_image_respects_model_selection(client):
    """Model selected in POST form is forwarded to generate_image."""
    with patch("app.image_gen.generate_image", return_value=b"png-bytes") as mock_gen, \
         patch("app.threading.Thread") as mock_thread:
        # Make Thread run the target synchronously instead of in background
        mock_thread.side_effect = lambda target, args, daemon: \
            type("T", (), {"start": lambda self: target(*args)})()

        client.post("/generate", data={
            "output_type": "image",
            "prompt": "a sunset",
            "image_model": "custom/model",
            "image_model_edit": "custom/edit-model",
        })

    assert mock_gen.called
    kwargs = mock_gen.call_args.kwargs
    assert kwargs.get("model") == "custom/model"
    assert kwargs.get("model_edit") == "custom/edit-model"


def test_status_pending(client):
    job_id = job_store.create_job()
    resp = client.get(f"/status/{job_id}")
    assert resp.status_code == 200


def test_status_done_image(client):
    job_id = job_store.create_job()
    job_store.update_job(job_id, {"status": "done", "output_type": "image", "data": b"png"})
    resp = client.get(f"/status/{job_id}")
    assert resp.status_code == 200


def test_download_image(client):
    job_id = job_store.create_job()
    job_store.update_job(job_id, {"status": "done", "output_type": "image", "data": b"png-content"})
    resp = client.get(f"/image/{job_id}")
    assert resp.status_code == 200
    assert resp.data == b"png-content"


def test_download_missing_job(client):
    resp = client.get("/image/nonexistent-id")
    assert resp.status_code == 404




def test_generate_rejects_more_than_10_images(client):
    """POST with 11 image files returns 400."""
    files = [
        ("images", (io.BytesIO(b"\x89PNG" + b"\x00" * 100), f"img{i}.png"))
        for i in range(11)
    ]
    data = MultiDict([("output_type", "image"), ("prompt", "test")] + files)
    resp = client.post(
        "/generate",
        data=data,
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_generate_skips_oversized_files(client, monkeypatch):
    """Files exceeding size limit are skipped, remaining files are processed."""
    monkeypatch.setattr("app._MAX_FILE_SIZE", 100)  # 100 bytes for test
    big = b"\x89PNG" + b"\x00" * 200  # 204 bytes, over the 100-byte test limit
    small = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50  # 58 bytes, under limit

    files = [
        ("images", (io.BytesIO(big), "big.png")),
        ("images", (io.BytesIO(small), "small.png")),
    ]
    data = MultiDict([("output_type", "image"), ("prompt", "test")] + files)

    with patch("app.image_gen.generate_image", return_value=b"png-bytes") as mock_gen, \
         patch("app.threading.Thread") as mock_thread:
        mock_thread.side_effect = lambda target, args, daemon: \
            type("T", (), {"start": lambda self: target(*args)})()

        resp = client.post(
            "/generate",
            data=data,
            content_type="multipart/form-data",
        )

    assert resp.status_code == 200
    assert mock_gen.called
    images_arg = mock_gen.call_args.kwargs.get("images") or mock_gen.call_args.args[2]
    assert len(images_arg) == 1
    assert len(images_arg[0]) == len(small)


def test_generate_empty_filename_filtered(client):
    """Files with empty filenames are filtered out."""
    files = [
        ("images", (io.BytesIO(b""), "")),
        ("images", (io.BytesIO(b"\x89PNG\r\n\x1a\n"), "real.png")),
    ]
    data = MultiDict([("output_type", "image"), ("prompt", "test")] + files)

    with patch("app.image_gen.generate_image", return_value=b"png-bytes") as mock_gen, \
         patch("app.threading.Thread") as mock_thread:
        mock_thread.side_effect = lambda target, args, daemon: \
            type("T", (), {"start": lambda self: target(*args)})()

        resp = client.post(
            "/generate",
            data=data,
            content_type="multipart/form-data",
        )

    assert resp.status_code == 200
    assert mock_gen.called
    images_arg = mock_gen.call_args.kwargs.get("images") or mock_gen.call_args.args[2]
    assert len(images_arg) == 1


def test_generate_no_images_sends_empty_list(client):
    """POST with no image files passes images=[] to the service."""
    with patch("app.image_gen.generate_image", return_value=b"png-bytes") as mock_gen, \
         patch("app.threading.Thread") as mock_thread:
        mock_thread.side_effect = lambda target, args, daemon: \
            type("T", (), {"start": lambda self: target(*args)})()

        resp = client.post("/generate", data={
            "output_type": "image",
            "prompt": "text only",
        })

    assert resp.status_code == 200
    assert mock_gen.called
    images_arg = mock_gen.call_args.kwargs.get("images") or mock_gen.call_args.args[2]
    assert images_arg == []


def test_generate_exactly_10_images_succeeds(client):
    """POST with exactly 10 image files returns 200 (boundary test)."""
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    files = [
        ("images", (io.BytesIO(png), f"img{i}.png"))
        for i in range(10)
    ]
    data = MultiDict([("output_type", "image"), ("prompt", "test")] + files)

    with patch("app.image_gen.generate_image", return_value=b"png-bytes") as mock_gen, \
         patch("app.threading.Thread") as mock_thread:
        mock_thread.side_effect = lambda target, args, daemon: \
            type("T", (), {"start": lambda self: target(*args)})()

        resp = client.post(
            "/generate",
            data=data,
            content_type="multipart/form-data",
        )

    assert resp.status_code == 200
    images_arg = mock_gen.call_args.kwargs.get("images") or mock_gen.call_args.args[2]
    assert len(images_arg) == 10


def test_generate_multiple_images_passed(client):
    """POST with 3 images passes all 3 to the service."""
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    files = [
        ("images", (io.BytesIO(png), "a.png")),
        ("images", (io.BytesIO(png), "b.png")),
        ("images", (io.BytesIO(png), "c.png")),
    ]
    data = MultiDict([("output_type", "image"), ("prompt", "blend")] + files)

    with patch("app.image_gen.generate_image", return_value=b"png-bytes") as mock_gen, \
         patch("app.threading.Thread") as mock_thread:
        mock_thread.side_effect = lambda target, args, daemon: \
            type("T", (), {"start": lambda self: target(*args)})()

        resp = client.post(
            "/generate",
            data=data,
            content_type="multipart/form-data",
        )

    assert resp.status_code == 200
    images_arg = mock_gen.call_args.kwargs.get("images") or mock_gen.call_args.args[2]
    assert len(images_arg) == 3


def test_generate_dashscope_image(client, cfg):
    """Full pipeline: POST /generate with dashscope image backend."""
    from config import ImageBackend
    cfg.image_backends["dashscope"] = ImageBackend(
        name="dashscope",
        api_url="https://ws.example.com/api/v1/services/aigc/multimodal-generation/generation",
        api_key="sk-test",
        model=["wan2.7-image"],
        model_edit=["wan2.7-image"],
        api_version="",
    )

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "output": {
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "content": [{"type": "image", "image": "https://cdn.example.com/img.png"}]
                }
            }]
        },
        "request_id": "req-1",
    }
    mock_resp.raise_for_status = MagicMock()

    mock_img = MagicMock()
    mock_img.content = b"\x89PNG\r\n\x1a\nfake-png"
    mock_img.raise_for_status = MagicMock()

    with patch("services.image_gen._requests.post", return_value=mock_resp), \
         patch("services.image_gen._requests.get", return_value=mock_img), \
         patch("app.threading.Thread") as mock_thread:
        mock_thread.side_effect = lambda target, args, daemon: \
            type("T", (), {"start": lambda self: target(*args)})()
        resp = client.post("/generate", data={
            "output_type": "image",
            "prompt": "a cat wearing a hat",
            "image_backend": "dashscope",
        })

    assert resp.status_code == 200
    assert b"Generating" in resp.data


def test_generate_unknown_image_backend_returns_400(client):
    resp = client.post("/generate", data={
        "output_type": "image",
        "prompt": "a cat",
        "image_backend": "does-not-exist",
    })
    assert resp.status_code == 400


def test_generate_forwards_selected_backend(client, cfg):
    from config import ImageBackend
    cfg.image_backends["fal"] = ImageBackend(
        name="fal",
        api_url="https://fal.run",
        api_key="fal-key",
        model=["fal-model"],
        model_edit=["fal-edit-model"],
        api_version="",
    )

    with patch("app.image_gen.generate_image", return_value=b"png-bytes") as mock_gen, \
         patch("app.threading.Thread") as mock_thread:
        mock_thread.side_effect = lambda target, args, daemon: \
            type("T", (), {"start": lambda self: target(*args)})()

        client.post("/generate", data={
            "output_type": "image",
            "prompt": "a sunset",
            "image_backend": "fal",
        })

    assert mock_gen.called
    kwargs = mock_gen.call_args.kwargs
    assert kwargs.get("backend") == "fal"
    assert kwargs.get("model") == "fal-model"
    assert kwargs.get("model_edit") == "fal-edit-model"


def test_index_hides_backend_select_with_one_backend(client):
    resp = client.get("/")
    assert b'name="image_backend"' not in resp.data


def test_index_shows_backend_select_with_multiple_backends():
    from app import create_app
    from config import Config, ImageBackend
    cfg = Config(
        image_backends={
            "openai": ImageBackend(
                name="openai", api_url="https://a", api_key="k",
                model=["m1"], model_edit=["m1"], api_version="",
            ),
            "fal": ImageBackend(
                name="fal", api_url="https://b", api_key="k2",
                model=["m2"], model_edit=["m2"], api_version="",
            ),
        },
        image_default_backend="openai",
        video_backend="fal", video_api_url="https://v", video_api_key="k",
        video_api_version="", video_azure_path="",
        video_model_image=["m"], video_model_text=["m"],
        secret_key="s", sd_api_url="", sd_model="",
    )
    app = create_app(cfg)
    app.config["TESTING"] = True
    test_client = app.test_client()
    resp = test_client.get("/")
    assert b'name="image_backend"' in resp.data


def test_generate_records_prompt_in_history(client):
    from services import prompt_store

    with patch("app.image_gen.generate_image", return_value=b"png-bytes"), \
         patch("app.threading.Thread") as mock_thread:
        mock_thread.side_effect = lambda target, args, daemon: \
            type("T", (), {"start": lambda self: target(*args)})()
        client.post("/generate", data={
            "output_type": "image",
            "prompt": "a lighthouse at dusk",
        })

    assert "a lighthouse at dusk" in [r.text for r in prompt_store.recent()]


def test_generate_skips_prompt_when_request_is_rejected(client):
    """A rejected request should not bump use_count — retrying a bad backend
    2× would otherwise pin the prompt into favourites."""
    from services import prompt_store

    resp = client.post("/generate", data={
        "output_type": "image",
        "prompt": "rejected but forgettable",
        "image_backend": "does-not-exist",
    })

    assert resp.status_code == 400
    assert "rejected but forgettable" not in [r.text for r in prompt_store.recent()]


def test_generate_does_not_record_blank_prompt(client):
    from services import prompt_store

    with patch("app.image_gen.generate_image", return_value=b"png-bytes"), \
         patch("app.threading.Thread") as mock_thread:
        mock_thread.side_effect = lambda target, args, daemon: \
            type("T", (), {"start": lambda self: target(*args)})()
        client.post("/generate", data={
            "output_type": "image",
            "prompt": "   ",
        })

    assert prompt_store.recent() == []


def test_extend_shows_the_search_box(client):
    body = client.get("/extend").data.decode()

    assert 'id="prompt-search"' in body
    assert 'name="q"' in body


def test_extend_lists_a_stored_prompt_as_a_button(client):
    from services import prompt_store

    prompt_store.add("a previously used prompt")
    body = client.get("/extend").data.decode()

    assert 'data-prompt="a previously used prompt"' in body
    assert 'id="prompt-history"' not in body


def test_picker_is_outside_the_generate_form(client):
    """Inside the form, the search box would be serialised into POST /generate
    as a stray `q` field. /generate ignores unknown fields, so nothing would
    visibly break — which is exactly why this needs a test."""
    body = client.get("/extend").data.decode()

    assert body.index('id="prompt-search"') < body.index('hx-post="/generate"')


def test_extend_renders_long_prompt_in_data_attribute(client):
    from services import prompt_store

    long_prompt = "z" * 1000
    prompt_store.add(long_prompt)
    body = client.get("/extend").data.decode()

    # data-prompt carries the full text...
    assert f'data-prompt="{long_prompt}"' in body
    # ...but the visible snippet is shorter than the full text.
    assert f'>{long_prompt}<' not in body


def test_extend_escapes_history_entries(client):
    from services import prompt_store

    prompt_store.add('<script>alert("x")</script>')
    body = client.get("/extend").data.decode()
    assert "<script>alert" not in body
    assert "&lt;script&gt;" in body


def test_extend_escapes_quote_in_history_entry(client):
    from services import prompt_store

    prompt_store.add('a " onmouseover="alert(1)')
    body = client.get("/extend").data.decode()
    assert 'onmouseover="' not in body


def test_extend_preserves_newlines_in_data_attribute(client):
    from services import prompt_store

    prompt_store.add("line one\nline two")
    body = client.get("/extend").data.decode()

    # The data-prompt attribute keeps the full text, newline included.
    assert 'data-prompt="line one\nline two"' in body


def test_generate_does_not_write_into_the_project_root(client):
    """The assertion whose absence let the suite destroy the real .cache/.

    Deliberately does NOT patch _cache_artifact — the real one must run, or
    this proves nothing. It DOES run the job synchronously, because a
    background thread could otherwise still be in flight when the assertions
    run, and the canary would pass on a race rather than on correctness.
    """
    import app

    root = app._DATA_DIR
    cache_dir = root / ".cache"
    created_cache_dir = (not cache_dir.exists())
    cache_dir.mkdir(exist_ok=True)
    # This plants a real file in the real data directory, outside any test
    # fixture's isolation, to prove the app under test can't touch it. If
    # the process is hard-killed between here and the `finally` below,
    # CANARY-leak-test is left behind in the real .cache/ and must be
    # removed by hand.
    canary = cache_dir / "CANARY-leak-test"
    canary.write_text("planted by the leak canary test")
    entries_before = set(cache_dir.rglob("*"))
    db_path = (root / "prompts.db")
    db_before = db_path.read_bytes() if db_path.exists() else None

    try:
        with patch("app.image_gen.generate_image", return_value=b"png-bytes"), \
             patch("app.threading.Thread") as mock_thread:
            mock_thread.side_effect = lambda target, args, daemon: \
                type("T", (), {"start": lambda self: target(*args)})()
            client.post("/generate", data={
                "output_type": "image",
                "prompt": "leak canary prompt",
            })
        client.get("/")

        assert canary.exists(), "the suite deleted files from the real .cache/"
        assert set(cache_dir.rglob("*")) == entries_before, \
            "the real .cache/ changed during the test — a leak, or the app running concurrently?"
        db_after = db_path.read_bytes() if db_path.exists() else None
        assert db_after == db_before, \
            "the suite wrote into the project root's prompts.db"
    finally:
        canary.unlink(missing_ok=True)
        if (created_cache_dir and cache_dir.exists() and (not any(cache_dir.iterdir()))):
            cache_dir.rmdir()


def test_prompts_endpoint_lists_recent_when_no_query(client):
    from services import prompt_store

    prompt_store.add("a previously used prompt")
    resp = client.get("/prompts")

    assert resp.status_code == 200
    assert b"a previously used prompt" in resp.data


def test_prompts_endpoint_filters_by_query(client):
    from services import prompt_store

    prompt_store.add("a red bikini")
    prompt_store.add("a blue coat")

    body = client.get("/prompts?q=bikini").data.decode()

    assert "a red bikini" in body
    assert "a blue coat" not in body


def test_prompts_endpoint_marks_the_match(client):
    from services import prompt_store

    prompt_store.add("a red bikini")

    body = client.get("/prompts?q=bikini").data.decode()

    assert "<mark" in body
    assert ">bikini</mark>" in body


def test_prompts_endpoint_reports_an_invalid_pattern_without_erroring(client):
    from services import prompt_store

    prompt_store.add("anything")
    resp = client.get("/prompts?q=/foo(/")

    assert resp.status_code == 200
    assert b"anything" not in resp.data
    assert b"Invalid regular expression." in resp.data


def test_min_use_count_hides_rare_prompts_from_the_list_but_not_from_search(client, cfg):
    """The central design decision, and the only thing keeping the counter
    honest: the cutoff trims the default list and nothing else."""
    from services import prompt_store

    cfg.prompt_min_use_count = 3
    prompt_store.add("used exactly once")

    assert b"used exactly once" not in client.get("/prompts").data
    assert b"used exactly once" in client.get("/prompts?q=exactly").data


def test_min_use_count_hides_from_pinned_block_too(client, cfg):
    """top() and recent() must agree: a prompt below the cutoff must not
    appear in either the favourites block or the recent list."""
    from services import prompt_store

    cfg.prompt_min_use_count = 3
    prompt_store.add("used twice")
    prompt_store.add("used twice")

    body = client.get("/prompts").data.decode()
    assert 'data-prompt="used twice"' not in body


def test_blank_query_is_treated_as_no_query_not_as_no_matches(client):
    """htmx sends ?q=%20 for a lone space. A raw truthiness check would
    render 'no matches' for what the user sees as an empty box."""
    from services import prompt_store

    prompt_store.add("a previously used prompt")

    assert b"a previously used prompt" in client.get("/prompts?q=%20").data


def test_pinned_prompts_are_not_repeated_in_the_recent_list(client):
    from services import prompt_store

    prompt_store.add("a favourite")
    prompt_store.add("a favourite")
    prompt_store.add("a one-off")

    body = client.get("/prompts").data.decode()

    # Count the attribute, not the bare text: each row renders the prompt
    # three times over (data-prompt, title, and the visible chunk), so
    # body.count("a favourite") is 3 even when the dedup is working.
    assert body.count('data-prompt="a favourite"') == 1


def test_prompt_html_is_escaped_in_the_results(client):
    from services import prompt_store

    prompt_store.add('<script>alert("x")</script>')

    body = client.get("/prompts").data.decode()

    assert "<script>alert" not in body
    assert "&lt;script&gt;" in body


def test_extend_renders_the_results_partial_on_first_paint(client):
    from services import prompt_store

    prompt_store.add("a previously used prompt")
    body = client.get("/extend").data.decode()

    assert 'id="prompt-results"' in body
    assert "a previously used prompt" in body


def test_picker_is_absent_on_root_route(client):
    """Root route never shows the picker, regardless of database state."""
    from services import prompt_store

    prompt_store.add("a previously used prompt")
    body = client.get("/").data.decode()

    # Assert on the attribute pattern, not the bare string: the JS contains
    # 'button[data-prompt]' as a selector, which would false-positive.
    assert 'data-prompt="' not in body
    assert 'id="prompt-search"' not in body
