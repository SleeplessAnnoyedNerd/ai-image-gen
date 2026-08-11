import base64
from unittest.mock import MagicMock, patch, call
from services.video_gen import start_video_job, poll_video_job


def _mock_post(request_id="req-123"):
    resp = MagicMock()
    resp.json.return_value = {
        "request_id": request_id,
        "status_url": "http://s",
        "response_url": "http://r",
    }
    resp.raise_for_status = MagicMock()
    return resp


def _mock_status(status="IN_QUEUE"):
    resp = MagicMock()
    resp.json.return_value = {"status": status}
    resp.raise_for_status = MagicMock()
    return resp


def _mock_result(video_url="https://cdn.fal.ai/video.mp4"):
    resp = MagicMock()
    resp.json.return_value = {"video": {"url": video_url}}
    resp.raise_for_status = MagicMock()
    return resp


def test_start_text_to_video(cfg):
    with patch("services.video_gen.requests.post", return_value=_mock_post()) as mock_post:
        result = start_video_job(cfg, prompt="a flying bird", images=[])

    call_args = mock_post.call_args
    assert cfg.video_model_text[0] in call_args.args[0]
    payload = call_args.kwargs["json"]
    assert payload["prompt"] == "a flying bird"
    assert "image_url" not in payload
    assert result["request_id"] == "req-123"


def test_start_image_to_video(cfg):
    with patch("services.video_gen.requests.post", return_value=_mock_post()) as mock_post:
        result = start_video_job(cfg, prompt="slow zoom", images=[b"\xff\xd8\xff\xe0fake-jpeg-data"])

    call_args = mock_post.call_args
    assert cfg.video_model_image[0] in call_args.args[0]
    payload = call_args.kwargs["json"]
    assert "image_url" in payload
    assert payload["image_url"].startswith("data:image/jpeg;base64,")
    assert result["request_id"] == "req-123"


def test_poll_pending(cfg):
    submit = {"status_url": "http://s", "response_url": "http://r"}
    with patch("services.video_gen.requests.get", return_value=_mock_status("IN_QUEUE")):
        result = poll_video_job(cfg, submit)
    assert result["status"] == "pending"


def test_poll_done(cfg):
    submit = {"status_url": "http://s", "response_url": "http://r"}
    status_resp = _mock_status("COMPLETED")
    result_resp = _mock_result("https://cdn.fal.ai/video.mp4")

    video_resp = MagicMock()
    video_resp.content = b"fake-mp4-bytes"
    video_resp.raise_for_status = MagicMock()

    with patch("services.video_gen.requests.get", side_effect=[status_resp, result_resp, video_resp]):
        result = poll_video_job(cfg, submit)
    assert result == {"status": "done", "video_data": b"fake-mp4-bytes"}


def test_poll_failed(cfg):
    submit = {"status_url": "http://s", "response_url": "http://r"}
    with patch("services.video_gen.requests.get", return_value=_mock_status("FAILED")):
        result = poll_video_job(cfg, submit)
    assert result["status"] == "error"


def test_start_fal_uses_cfg_default_text_model(cfg):
    with patch("services.video_gen.requests.post") as mock_post:
        mock_post.return_value.json.return_value = {
            "request_id": "r1", "status_url": "http://s", "response_url": "http://r"
        }
        mock_post.return_value.raise_for_status = lambda: None

        from services.video_gen import start_video_job
        start_video_job(cfg, prompt="flying bird", images=[])

        url_called = mock_post.call_args[0][0]
        assert cfg.video_model_text[0] in url_called


def test_start_fal_uses_explicit_model_text(cfg):
    with patch("services.video_gen.requests.post") as mock_post:
        mock_post.return_value.json.return_value = {
            "request_id": "r1", "status_url": "http://s", "response_url": "http://r"
        }
        mock_post.return_value.raise_for_status = lambda: None

        from services.video_gen import start_video_job
        start_video_job(cfg, prompt="flying bird", images=[], model_text="custom/vid")

        url_called = mock_post.call_args[0][0]
        assert "custom/vid" in url_called


def test_start_fal_uses_explicit_model_image(cfg):
    with patch("services.video_gen.requests.post") as mock_post:
        mock_post.return_value.json.return_value = {
            "request_id": "r1", "status_url": "http://s", "response_url": "http://r"
        }
        mock_post.return_value.raise_for_status = lambda: None

        from services.video_gen import start_video_job
        start_video_job(cfg, prompt="flying bird", images=[b"img"], model_image="custom/img-vid")

        url_called = mock_post.call_args[0][0]
        assert "custom/img-vid" in url_called


# --- DashScope backend tests ---

from config import Config
import pytest


def _dashscope_video_cfg():
    """Helper to create a Config with dashscope video backend."""
    return Config(
        image_backends={}, image_default_backend="",
        video_backend="dashscope",
        video_api_url="https://ws-c2xbh4slyhwu4ifn.ap-southeast-1.maas.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis",
        video_api_key="sk-test-key",
        video_api_version="", video_azure_path="",
        video_model_image=["wan2.7-r2v"],
        video_model_text=["wan2.7-t2v"],
        secret_key="test", sd_api_url="", sd_model="",
    )


def test_dashscope_start_text_to_video():
    """DashScope backend: text-only video submission."""
    cfg = _dashscope_video_cfg()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "output": {"task_id": "task-abc", "task_status": "PENDING"},
        "request_id": "req-789",
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("services.video_gen.requests.post", return_value=mock_resp) as mock_post:
        result = start_video_job(cfg, prompt="a cat walking", images=[])

    assert result == {"task_id": "task-abc"}

    # Verify correct model and payload
    payload = mock_post.call_args.kwargs["json"]
    assert payload["model"] == "wan2.7-t2v"
    assert payload["input"]["prompt"] == "a cat walking"
    assert "media" not in payload["input"]
    assert payload["parameters"]["watermark"] is False
    assert payload["parameters"]["resolution"] == "720P"


def test_dashscope_start_image_to_video():
    """DashScope backend: reference image video submission."""
    cfg = _dashscope_video_cfg()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "output": {"task_id": "task-def", "task_status": "PENDING"},
        "request_id": "req-101",
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("services.video_gen.requests.post", return_value=mock_resp) as mock_post:
        result = start_video_job(cfg, prompt="slow zoom", images=[b"\x89PNG\r\n\x1a\nfake"])

    assert result == {"task_id": "task-def"}

    # Verify correct model and payload includes media
    payload = mock_post.call_args.kwargs["json"]
    assert payload["model"] == "wan2.7-r2v"
    assert len(payload["input"]["media"]) == 1
    assert payload["input"]["media"][0]["type"] == "reference_image"
    assert payload["input"]["media"][0]["url"].startswith("data:image/png;base64,")


def test_dashscope_poll_pending():
    """DashScope backend: poll returns pending status."""
    cfg = _dashscope_video_cfg()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "output": {"task_id": "task-abc", "task_status": "RUNNING"},
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("services.video_gen.requests.get", return_value=mock_resp):
        result = poll_video_job(cfg, {"task_id": "task-abc"})

    assert result["status"] == "pending"


def test_dashscope_poll_done():
    """DashScope backend: poll returns done with video data."""
    cfg = _dashscope_video_cfg()

    mock_poll_resp = MagicMock()
    mock_poll_resp.status_code = 200
    mock_poll_resp.json.return_value = {
        "output": {
            "task_id": "task-abc",
            "task_status": "SUCCEEDED",
            "video_url": "https://cdn.example.com/video.mp4",
        },
    }
    mock_poll_resp.raise_for_status = MagicMock()

    mock_video_resp = MagicMock()
    mock_video_resp.content = b"fake-mp4-data"
    mock_video_resp.raise_for_status = MagicMock()

    with patch("services.video_gen.requests.get", side_effect=[mock_poll_resp, mock_video_resp]):
        result = poll_video_job(cfg, {"task_id": "task-abc"})

    assert result == {"status": "done", "video_data": b"fake-mp4-data"}


def test_dashscope_poll_failed():
    """DashScope backend: poll returns error on failure."""
    cfg = _dashscope_video_cfg()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "output": {"task_id": "task-abc", "task_status": "FAILED"},
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("services.video_gen.requests.get", return_value=mock_resp):
        result = poll_video_job(cfg, {"task_id": "task-abc"})

    assert result["status"] == "error"


def test_dashscope_poll_canceled():
    """DashScope backend: poll returns error on CANCELED status."""
    cfg = _dashscope_video_cfg()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "output": {"task_id": "task-abc", "task_status": "CANCELED"},
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("services.video_gen.requests.get", return_value=mock_resp):
        result = poll_video_job(cfg, {"task_id": "task-abc"})

    assert result["status"] == "error"
    assert "CANCELED" in result["message"]


def test_dashscope_missing_config_raises():
    """DashScope backend: raises ValueError when config is missing."""
    cfg = Config(
        image_backends={}, image_default_backend="",
        video_backend="dashscope", video_api_url="", video_api_key="",
        video_api_version="", video_azure_path="",
        video_model_image=["wan2.7-r2v"], video_model_text=["wan2.7-t2v"],
        secret_key="test", sd_api_url="", sd_model="",
    )
    with pytest.raises(ValueError, match="VIDEO_API_URL"):
        start_video_job(cfg, prompt="a cat", images=[])


def test_dashscope_multi_image_video_media():
    """DashScope: 3 images with wan2.7 model produce 3 media[] entries."""
    cfg = _dashscope_video_cfg()
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
    jpg = b"\xff\xd8\xff\xe0" + b"\x00" * 50
    png2 = b"\x89PNG\r\n\x1a\n" + b"\xff" * 50

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "output": {"task_id": "task-multi", "task_status": "PENDING"},
        "request_id": "req-multi",
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("services.video_gen.requests.post", return_value=mock_resp) as mock_post:
        result = start_video_job(cfg, prompt="blend these", images=[png, jpg, png2])

    assert result == {"task_id": "task-multi"}
    payload = mock_post.call_args.kwargs["json"]
    assert payload["model"] == "wan2.7-r2v"
    assert len(payload["input"]["media"]) == 3
    assert payload["input"]["media"][0]["url"].startswith("data:image/png;base64,")
    assert payload["input"]["media"][1]["url"].startswith("data:image/jpeg;base64,")
    assert payload["input"]["media"][2]["url"].startswith("data:image/png;base64,")


def _dashscope_video_cfg_wan26():
    """Helper to create a Config with wan2.6 video model."""
    return Config(
        image_backends={}, image_default_backend="",
        video_backend="dashscope",
        video_api_url="https://ws-c2xbh4slyhwu4ifn.ap-southeast-1.maas.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis",
        video_api_key="sk-test-key",
        video_api_version="", video_azure_path="",
        video_model_image=["wan2.6-r2v"],
        video_model_text=["wan2.6-t2v"],
        secret_key="test", sd_api_url="", sd_model="",
    )


def test_dashscope_video_wan26_single_image_only():
    """DashScope: wan2.6 model sends only first image via img_url, no media[]."""
    cfg = _dashscope_video_cfg_wan26()
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
    jpg = b"\xff\xd8\xff\xe0" + b"\x00" * 50

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "output": {"task_id": "task-wan26", "task_status": "PENDING"},
        "request_id": "req-wan26",
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("services.video_gen.requests.post", return_value=mock_resp) as mock_post:
        result = start_video_job(cfg, prompt="animate", images=[png, jpg])

    assert result == {"task_id": "task-wan26"}
    payload = mock_post.call_args.kwargs["json"]
    assert payload["model"] == "wan2.6-r2v"
    assert "media" not in payload["input"]
    assert payload["input"]["img_url"].startswith("data:image/png;base64,")


def test_dashscope_video_zero_images():
    """DashScope: empty images list uses text model, no media/img_url."""
    cfg = _dashscope_video_cfg()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "output": {"task_id": "task-zero", "task_status": "PENDING"},
        "request_id": "req-zero",
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("services.video_gen.requests.post", return_value=mock_resp) as mock_post:
        result = start_video_job(cfg, prompt="a flying bird", images=[])

    payload = mock_post.call_args.kwargs["json"]
    assert payload["model"] == "wan2.7-t2v"
    assert "media" not in payload["input"]
    assert "img_url" not in payload["input"]


# --- Dummy backend tests ---


def _dummy_video_cfg():
    """Config with dummy video backend, isolated from the shared fixture."""
    return Config(
        image_backends={}, image_default_backend="",
        video_backend="dummy",
        video_api_url="https://unused.example.com",
        video_api_key="unused",
        video_api_version="", video_azure_path="",
        video_model_image=["m"], video_model_text=["m"],
        secret_key="test", sd_api_url="", sd_model="",
    )


def test_dummy_start_returns_fresh_counter():
    cfg = _dummy_video_cfg()
    result = start_video_job(cfg, prompt="a cat")
    assert result == {"dummy": True, "polls": 0}


def test_dummy_poll_sequence():
    """Pending twice (queue positions 2 then 1), then done with video data."""
    cfg = _dummy_video_cfg()
    submit = start_video_job(cfg, prompt="a cat")

    r1 = poll_video_job(cfg, submit)
    assert r1 == {"status": "pending", "queue_position": 2}

    r2 = poll_video_job(cfg, submit)
    assert r2 == {"status": "pending", "queue_position": 1}

    r3 = poll_video_job(cfg, submit)
    assert r3["status"] == "done"
    assert r3["video_data"][4:8] == b"ftyp"  # MP4 magic bytes


def test_dummy_poll_counter_independent():
    """Two submits do not share a poll counter."""
    cfg = _dummy_video_cfg()
    s1 = start_video_job(cfg, prompt="a")
    s2 = start_video_job(cfg, prompt="b")

    poll_video_job(cfg, s1)
    poll_video_job(cfg, s1)

    # s2 should still be at poll 0 -- not at poll 2
    r = poll_video_job(cfg, s2)
    assert r == {"status": "pending", "queue_position": 2}


def test_dummy_poll_completes_in_exactly_three_polls():
    cfg = _dummy_video_cfg()
    submit = start_video_job(cfg, prompt="a bird")
    for _ in range(2):
        poll_video_job(cfg, submit)
    result = poll_video_job(cfg, submit)
    assert result["status"] == "done"
    assert len(result["video_data"]) > 0
