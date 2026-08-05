import os
import shutil
from unittest.mock import patch
from datetime import datetime


def setup_function():
    if os.path.exists(".cache"):
        shutil.rmtree(".cache")


def teardown_function():
    if os.path.exists(".cache"):
        shutil.rmtree(".cache")


def test_cache_artifact_writes_file():
    from app import _cache_artifact

    fixed_time = datetime(2026, 8, 5, 15, 18, 0)
    with patch("app.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_time
        _cache_artifact("test-job-id", b"hello-bytes", "png")

    expected_path = ".cache/20260805/20260805-151800-test-job-id.png"
    assert os.path.exists(expected_path)
    with open(expected_path, "rb") as f:
        assert f.read() == b"hello-bytes"


def test_cache_artifact_creates_date_subdirectory():
    from app import _cache_artifact

    fixed_time = datetime(2026, 12, 25, 9, 30, 45)
    with patch("app.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_time
        _cache_artifact("job-abc", b"\x89PNG", "png")

    assert os.path.isdir(".cache/20261225")
    assert os.path.exists(".cache/20261225/20261225-093045-job-abc.png")


def test_cache_artifact_video_extension():
    from app import _cache_artifact

    fixed_time = datetime(2026, 1, 1, 0, 0, 0)
    with patch("app.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_time
        _cache_artifact("vid-job", b"fake-mp4", "mp4")

    expected_path = ".cache/20260101/20260101-000000-vid-job.mp4"
    assert os.path.exists(expected_path)
