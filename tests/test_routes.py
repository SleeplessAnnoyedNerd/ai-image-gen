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


def test_generate_image_job_starts(client):
    with patch("app.image_gen.generate_image", return_value=b"png-bytes"):
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
         patch("services.image_gen._requests.get", return_value=mock_img):
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

    with patch("app.image_gen.generate_image", return_value=b"png-bytes"):
        client.post("/generate", data={
            "output_type": "image",
            "prompt": "a lighthouse at dusk",
        })

    assert "a lighthouse at dusk" in prompt_store.recent()


def test_generate_records_prompt_even_when_request_is_rejected(client):
    """A prompt is worth keeping even if the request 400s — it's the one
    you want to retry."""
    from services import prompt_store

    client.post("/generate", data={
        "output_type": "image",
        "prompt": "rejected but memorable",
        "image_backend": "does-not-exist",
    })

    assert "rejected but memorable" in prompt_store.recent()


def test_generate_does_not_record_blank_prompt(client):
    from services import prompt_store

    with patch("app.image_gen.generate_image", return_value=b"png-bytes"):
        client.post("/generate", data={
            "output_type": "image",
            "prompt": "   ",
        })

    assert prompt_store.recent() == []


def test_index_hides_history_select_when_empty(client):
    resp = client.get("/")
    assert b'id="prompt-history"' not in resp.data


def test_index_shows_history_select_when_populated(client):
    from services import prompt_store

    prompt_store.add("a previously used prompt")
    resp = client.get("/")
    assert b'id="prompt-history"' in resp.data
    assert b"a previously used prompt" in resp.data

    # The select must never be serialised into the form POST.
    body = resp.data.decode("utf-8")
    tag_start = body.index('<select id="prompt-history"')
    tag_end = body.index(">", tag_start)
    assert "name=" not in body[tag_start:tag_end]


def test_index_trims_long_history_labels(client):
    from services import prompt_store

    long_prompt = "z" * 100
    prompt_store.add(long_prompt)
    body = client.get("/").data.decode("utf-8")

    # Full text survives in the option value...
    assert f'value="{long_prompt}"' in body
    # ...but the visible label is trimmed to 40 chars plus an ellipsis.
    assert f'>{"z" * 40}…<' in body
    assert f'>{"z" * 41}' not in body


def test_index_escapes_history_entries(client):
    from services import prompt_store

    prompt_store.add('<script>alert("x")</script>')
    body = client.get("/").data.decode("utf-8")
    assert "<script>alert" not in body
    assert "&lt;script&gt;" in body


def test_index_escapes_quote_in_history_entry(client):
    from services import prompt_store

    prompt_store.add('a " onmouseover="alert(1)')
    body = client.get("/").data.decode("utf-8")
    assert 'onmouseover="' not in body
