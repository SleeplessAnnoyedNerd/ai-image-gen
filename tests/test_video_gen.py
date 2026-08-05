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
        result = start_video_job(cfg, prompt="a flying bird", image_bytes=None)

    call_args = mock_post.call_args
    assert cfg.video_model_text[0] in call_args.args[0]
    payload = call_args.kwargs["json"]
    assert payload["prompt"] == "a flying bird"
    assert "image_url" not in payload
    assert result["request_id"] == "req-123"


def test_start_image_to_video(cfg):
    with patch("services.video_gen.requests.post", return_value=_mock_post()) as mock_post:
        result = start_video_job(cfg, prompt="slow zoom", image_bytes=b"img-data")

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
        start_video_job(cfg, prompt="flying bird", image_bytes=None)

        url_called = mock_post.call_args[0][0]
        assert cfg.video_model_text[0] in url_called


def test_start_fal_uses_explicit_model_text(cfg):
    with patch("services.video_gen.requests.post") as mock_post:
        mock_post.return_value.json.return_value = {
            "request_id": "r1", "status_url": "http://s", "response_url": "http://r"
        }
        mock_post.return_value.raise_for_status = lambda: None

        from services.video_gen import start_video_job
        start_video_job(cfg, prompt="flying bird", image_bytes=None, model_text="custom/vid")

        url_called = mock_post.call_args[0][0]
        assert "custom/vid" in url_called


def test_start_fal_uses_explicit_model_image(cfg):
    with patch("services.video_gen.requests.post") as mock_post:
        mock_post.return_value.json.return_value = {
            "request_id": "r1", "status_url": "http://s", "response_url": "http://r"
        }
        mock_post.return_value.raise_for_status = lambda: None

        from services.video_gen import start_video_job
        start_video_job(cfg, prompt="flying bird", image_bytes=b"img", model_image="custom/img-vid")

        url_called = mock_post.call_args[0][0]
        assert "custom/img-vid" in url_called


# --- DashScope backend tests ---

from config import Config
import pytest


def _dashscope_video_cfg():
    """Helper to create a Config with dashscope video backend."""
    return Config(
        image_api_url="", image_api_key="",
        image_model=[""], image_model_edit=[""],
        image_backend="openai", image_api_version="",
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
        result = start_video_job(cfg, prompt="a cat walking", image_bytes=None)

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
        result = start_video_job(cfg, prompt="slow zoom", image_bytes=b"\x89PNG\r\n\x1a\nfake")

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
        image_api_url="", image_api_key="",
        image_model=[""], image_model_edit=[""],
        image_backend="openai", image_api_version="",
        video_backend="dashscope", video_api_url="", video_api_key="",
        video_api_version="", video_azure_path="",
        video_model_image=["wan2.7-r2v"], video_model_text=["wan2.7-t2v"],
        secret_key="test", sd_api_url="", sd_model="",
    )
    with pytest.raises(ValueError, match="VIDEO_API_URL"):
        start_video_job(cfg, prompt="a cat", image_bytes=None)
