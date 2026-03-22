import base64
from unittest.mock import MagicMock, patch, call
from services.video_gen import start_video_job, poll_video_job


def _mock_post(request_id="req-123"):
    resp = MagicMock()
    resp.json.return_value = {"request_id": request_id}
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

    assert result == ("req-123", cfg.video_model_text)
    call_args = mock_post.call_args
    assert cfg.video_model_text in call_args.args[0]
    payload = call_args.kwargs["json"]
    assert payload["prompt"] == "a flying bird"
    assert "image_url" not in payload


def test_start_image_to_video(cfg):
    with patch("services.video_gen.requests.post", return_value=_mock_post()) as mock_post:
        result = start_video_job(cfg, prompt="slow zoom", image_bytes=b"img-data")

    assert result == ("req-123", cfg.video_model_image)
    payload = mock_post.call_args.kwargs["json"]
    assert "image_url" in payload
    assert payload["image_url"].startswith("data:image/jpeg;base64,")


def test_poll_pending(cfg):
    with patch("services.video_gen.requests.get", return_value=_mock_status("IN_QUEUE")):
        result = poll_video_job(cfg, "req-123", cfg.video_model_text)
    assert result == {"status": "pending"}


def test_poll_done(cfg):
    status_resp = _mock_status("COMPLETED")
    result_resp = _mock_result("https://cdn.fal.ai/video.mp4")
    with patch("services.video_gen.requests.get", side_effect=[status_resp, result_resp]):
        result = poll_video_job(cfg, "req-123", cfg.video_model_text)
    assert result == {"status": "done", "video_url": "https://cdn.fal.ai/video.mp4"}


def test_poll_failed(cfg):
    with patch("services.video_gen.requests.get", return_value=_mock_status("FAILED")):
        result = poll_video_job(cfg, "req-123", cfg.video_model_text)
    assert result["status"] == "error"
