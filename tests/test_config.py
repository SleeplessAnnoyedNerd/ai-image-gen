import pytest
from config import Config, _parse_list


# --- unit tests for _parse_list ---

def test_parse_list_single():
    assert _parse_list("model-a") == ["model-a"]


def test_parse_list_multiple():
    assert _parse_list("model-a, model-b , model-c") == ["model-a", "model-b", "model-c"]


def test_parse_list_strips_whitespace():
    assert _parse_list("  x  ,  y  ") == ["x", "y"]


def test_parse_list_ignores_empty_segments():
    assert _parse_list("a,,b") == ["a", "b"]


# --- Config.from_env ---

def _set_required_env(monkeypatch, overrides=None):
    defaults = {
        "IMAGE_API_URL": "https://img.example.com/v1",
        "IMAGE_API_KEY": "img-key",
        "IMAGE_MODEL": "my/image-model",
        "IMAGE_MODEL_EDIT": "my/edit-model",
        "VIDEO_API_URL": "https://vid.example.com",
        "VIDEO_API_KEY": "vid-key",
        "VIDEO_MODEL_IMAGE": "my/vid-img-model",
        "VIDEO_MODEL_TEXT": "my/vid-txt-model",
        "FLASK_SECRET_KEY": "s3cr3t",
    }
    if overrides:
        defaults.update(overrides)
    for k, v in defaults.items():
        monkeypatch.setenv(k, v)


def test_config_from_env_single_models(monkeypatch):
    _set_required_env(monkeypatch)
    cfg = Config.from_env()
    assert cfg.image_model == ["my/image-model"]
    assert cfg.image_model_edit == ["my/edit-model"]
    assert cfg.video_model_image == ["my/vid-img-model"]
    assert cfg.video_model_text == ["my/vid-txt-model"]


def test_config_from_env_multi_models(monkeypatch):
    _set_required_env(monkeypatch, {
        "IMAGE_MODEL": "model-a, model-b",
        "VIDEO_MODEL_TEXT": "vid-x,vid-y,vid-z",
    })
    cfg = Config.from_env()
    assert cfg.image_model == ["model-a", "model-b"]
    assert cfg.video_model_text == ["vid-x", "vid-y", "vid-z"]


def test_config_missing_required_var(monkeypatch):
    _set_required_env(monkeypatch)
    monkeypatch.delenv("IMAGE_API_KEY")
    with pytest.raises(EnvironmentError, match="IMAGE_API_KEY"):
        Config.from_env()


def test_config_missing_required_var_whitespace(monkeypatch):
    _set_required_env(monkeypatch)
    monkeypatch.setenv("IMAGE_API_KEY", "   ")
    with pytest.raises(EnvironmentError, match="IMAGE_API_KEY"):
        Config.from_env()
