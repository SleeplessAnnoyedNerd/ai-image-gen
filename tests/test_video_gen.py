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
    with patch("services.video_gen.requests.get", side_effect=[status_resp, result_resp]):
        result = poll_video_job(cfg, submit)
    assert result == {"status": "done", "video_url": "https://cdn.fal.ai/video.mp4"}


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
