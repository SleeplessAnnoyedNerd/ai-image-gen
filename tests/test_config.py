import os
import pytest
from config import Config


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("IMAGE_API_URL", "https://img.example.com/v1")
    monkeypatch.setenv("IMAGE_API_KEY", "img-key")
    monkeypatch.setenv("IMAGE_MODEL", "my/image-model")
    monkeypatch.setenv("VIDEO_API_URL", "https://vid.example.com")
    monkeypatch.setenv("VIDEO_API_KEY", "vid-key")
    monkeypatch.setenv("VIDEO_MODEL_IMAGE", "my/vid-img-model")
    monkeypatch.setenv("VIDEO_MODEL_TEXT", "my/vid-txt-model")
    monkeypatch.setenv("FLASK_SECRET_KEY", "s3cr3t")

    cfg = Config.from_env()

    assert cfg.image_api_url == "https://img.example.com/v1"
    assert cfg.image_api_key == "img-key"
    assert cfg.image_model == "my/image-model"
    assert cfg.video_api_url == "https://vid.example.com"
    assert cfg.video_api_key == "vid-key"
    assert cfg.video_model_image == "my/vid-img-model"
    assert cfg.video_model_text == "my/vid-txt-model"
    assert cfg.secret_key == "s3cr3t"


def test_config_missing_required_var(monkeypatch):
    monkeypatch.delenv("IMAGE_API_KEY", raising=False)
    with pytest.raises(EnvironmentError, match="IMAGE_API_KEY"):
        Config.from_env()
