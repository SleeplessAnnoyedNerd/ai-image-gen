import pytest
from config import Config, _parse_list, _load_toml, _merge, _require, _get


# --- unit tests for _parse_list ---

def test_parse_list_single():
    assert _parse_list("model-a") == ["model-a"]


def test_parse_list_multiple():
    assert _parse_list("model-a, model-b , model-c") == ["model-a", "model-b", "model-c"]


def test_parse_list_strips_whitespace():
    assert _parse_list("  x  ,  y  ") == ["x", "y"]


def test_parse_list_ignores_empty_segments():
    assert _parse_list("a,,b") == ["a", "b"]


def test_parse_list_from_toml_list():
    assert _parse_list(["model-a", "model-b"]) == ["model-a", "model-b"]


# --- unit tests for _load_toml ---

def test_load_toml_missing_file(tmp_path):
    result = _load_toml(str(tmp_path / "nonexistent.toml"))
    assert result == {}


def test_load_toml_existing_file(tmp_path):
    toml_file = tmp_path / "test.toml"
    toml_file.write_text('[section]\nkey = "value"\n')
    result = _load_toml(str(toml_file))
    assert result == {"section": {"key": "value"}}


def test_load_toml_malformed_raises(tmp_path):
    toml_file = tmp_path / "bad.toml"
    toml_file.write_text("[invalid\ntoml content")
    import tomllib
    with pytest.raises(tomllib.TOMLDecodeError):
        _load_toml(str(toml_file))


def test_load_toml_empty_file(tmp_path):
    """An empty TOML file is valid (returns empty dict)."""
    toml_file = tmp_path / "empty.toml"
    toml_file.write_text("")
    result = _load_toml(str(toml_file))
    assert result == {}


# --- unit tests for _merge ---

def test_merge_disjoint():
    assert _merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}


def test_merge_override():
    assert _merge({"a": 1}, {"a": 2}) == {"a": 2}


def test_merge_deep():
    base = {"s": {"a": 1, "b": 2}}
    override = {"s": {"b": 3, "c": 4}}
    assert _merge(base, override) == {"s": {"a": 1, "b": 3, "c": 4}}


# --- unit tests for _require / _get (via _settings patching) ---

def test_require_present_string(monkeypatch):
    import config as cfg_module
    monkeypatch.setattr(cfg_module, "_settings", {"section": {"key": "value"}})
    assert _require("section", "key") == "value"


def test_require_present_list(monkeypatch):
    import config as cfg_module
    monkeypatch.setattr(cfg_module, "_settings", {"section": {"key": ["a", "b"]}})
    assert _require("section", "key") == ["a", "b"]


def test_require_missing(monkeypatch):
    import config as cfg_module
    monkeypatch.setattr(cfg_module, "_settings", {})
    with pytest.raises(EnvironmentError, match="section.*key"):
        _require("section", "key")


def test_require_empty(monkeypatch):
    import config as cfg_module
    monkeypatch.setattr(cfg_module, "_settings", {"section": {"key": "   "}})
    with pytest.raises(EnvironmentError, match="section.*key"):
        _require("section", "key")


def test_require_empty_list(monkeypatch):
    import config as cfg_module
    monkeypatch.setattr(cfg_module, "_settings", {"section": {"key": []}})
    with pytest.raises(EnvironmentError, match="section.*key"):
        _require("section", "key")


def test_require_none(monkeypatch):
    import config as cfg_module
    monkeypatch.setattr(cfg_module, "_settings", {"section": {"key": None}})
    with pytest.raises(EnvironmentError, match="section.*key"):
        _require("section", "key")


def test_get_present(monkeypatch):
    import config as cfg_module
    monkeypatch.setattr(cfg_module, "_settings", {"section": {"key": "value"}})
    assert _get("section", "key") == "value"


def test_get_missing_default(monkeypatch):
    import config as cfg_module
    monkeypatch.setattr(cfg_module, "_settings", {})
    assert _get("section", "key", "fallback") == "fallback"


def test_get_none_returns_default(monkeypatch):
    import config as cfg_module
    monkeypatch.setattr(cfg_module, "_settings", {"section": {"key": None}})
    assert _get("section", "key", "fallback") == "fallback"


# --- Config.from_settings ---

def _patch_settings(monkeypatch, settings_data, secrets_data=None):
    """Patch config._settings with merged test data."""
    import config as cfg_module
    base = settings_data or {}
    override = secrets_data or {}
    merged = _merge(base, override)
    monkeypatch.setattr(cfg_module, "_settings", merged)


def test_from_settings_single_backend_single_models(monkeypatch):
    _patch_settings(monkeypatch, {
        "flask": {"secret_key": "s3cr3t", "port": 5005},
        "image": {
            "default_backend": "openai",
            "openai": {
                "api_url": "https://img.example.com/v1",
                "model": ["my/image-model"],
                "model_edit": ["my/edit-model"],
            },
        },
        "video": {
            "api_url": "https://vid.example.com",
            "model_image": ["my/vid-img-model"],
            "model_text": ["my/vid-txt-model"],
        },
    }, {
        "image": {"openai": {"api_key": "img-key"}},
        "video": {"api_key": "vid-key"},
    })
    cfg = Config.from_settings()
    assert set(cfg.image_backends.keys()) == {"openai"}
    bc = cfg.image_backends["openai"]
    assert bc.model == ["my/image-model"]
    assert bc.model_edit == ["my/edit-model"]
    assert bc.api_key == "img-key"
    assert cfg.image_default_backend == "openai"
    assert cfg.video_model_image == ["my/vid-img-model"]
    assert cfg.video_model_text == ["my/vid-txt-model"]
    assert cfg.secret_key == "s3cr3t"


def test_from_settings_multiple_backends(monkeypatch):
    _patch_settings(monkeypatch, {
        "flask": {"secret_key": "s3cr3t", "port": 5005},
        "image": {
            "default_backend": "fal",
            "dashscope": {
                "api_url": "https://img.example.com/v1",
                "model": ["model-a", "model-b"],
                "model_edit": ["edit-a"],
            },
            "fal": {
                "api_url": "https://fal.run",
                "model": ["fal-model"],
                "model_edit": ["fal-edit-model"],
            },
        },
        "video": {
            "api_url": "https://vid.example.com",
            "model_image": ["my/vid-img-model"],
            "model_text": ["vid-x", "vid-y", "vid-z"],
        },
    }, {
        "image": {
            "dashscope": {"api_key": "ds-key"},
            "fal": {"api_key": "fal-key"},
        },
        "video": {"api_key": "vid-key"},
    })
    cfg = Config.from_settings()
    assert set(cfg.image_backends.keys()) == {"dashscope", "fal"}
    assert cfg.image_backends["dashscope"].model == ["model-a", "model-b"]
    assert cfg.image_backends["fal"].model == ["fal-model"]
    assert cfg.image_default_backend == "fal"
    assert cfg.video_model_text == ["vid-x", "vid-y", "vid-z"]


def test_from_settings_backend_without_api_key_excluded(monkeypatch):
    _patch_settings(monkeypatch, {
        "flask": {"secret_key": "s3cr3t", "port": 5005},
        "image": {
            "default_backend": "dashscope",
            "dashscope": {
                "api_url": "https://img.example.com/v1",
                "model": ["m"],
                "model_edit": ["m"],
            },
            "fal": {
                "api_url": "https://fal.run",
                "model": ["fal-model"],
                "model_edit": ["fal-edit"],
            },
        },
        "video": {
            "api_url": "https://vid.example.com",
            "model_image": ["m"],
            "model_text": ["m"],
        },
    }, {
        "image": {"dashscope": {"api_key": "ds-key"}},
        "video": {"api_key": "vid-key"},
    })
    cfg = Config.from_settings()
    assert set(cfg.image_backends.keys()) == {"dashscope"}


def test_from_settings_default_backend_falls_back(monkeypatch):
    _patch_settings(monkeypatch, {
        "flask": {"secret_key": "s3cr3t", "port": 5005},
        "image": {
            "dashscope": {
                "api_url": "https://img.example.com/v1",
                "model": ["m"],
                "model_edit": ["m"],
            },
        },
        "video": {
            "api_url": "https://vid.example.com",
            "model_image": ["m"],
            "model_text": ["m"],
        },
    }, {
        "image": {"dashscope": {"api_key": "ds-key"}},
        "video": {"api_key": "vid-key"},
    })
    cfg = Config.from_settings()
    assert cfg.image_default_backend == "dashscope"


def test_from_settings_no_image_backends_raises(monkeypatch):
    _patch_settings(monkeypatch, {
        "flask": {"secret_key": "s3cr3t", "port": 5005},
        "image": {
            "dashscope": {
                "api_url": "https://img.example.com/v1",
                "model": ["m"],
                "model_edit": ["m"],
            },
        },
        "video": {
            "api_url": "https://vid.example.com",
            "model_image": ["m"],
            "model_text": ["m"],
        },
    }, {
        "video": {"api_key": "vid-key"},
    })
    with pytest.raises(EnvironmentError, match=r"No \[image\.\*\] backend"):
        Config.from_settings()


def test_from_settings_backend_missing_models_raises(monkeypatch):
    _patch_settings(monkeypatch, {
        "flask": {"secret_key": "s3cr3t", "port": 5005},
        "image": {
            "dashscope": {
                "api_url": "https://img.example.com/v1",
            },
        },
        "video": {
            "api_url": "https://vid.example.com",
            "model_image": ["m"],
            "model_text": ["m"],
        },
    }, {
        "image": {"dashscope": {"api_key": "ds-key"}},
        "video": {"api_key": "vid-key"},
    })
    with pytest.raises(EnvironmentError, match="dashscope.*model"):
        Config.from_settings()


def test_from_settings_backend_missing_api_url_raises(monkeypatch):
    _patch_settings(monkeypatch, {
        "flask": {"secret_key": "s3cr3t", "port": 5005},
        "image": {
            "dashscope": {
                "model": ["m"],
                "model_edit": ["m"],
            },
        },
        "video": {
            "api_url": "https://vid.example.com",
            "model_image": ["m"],
            "model_text": ["m"],
        },
    }, {
        "image": {"dashscope": {"api_key": "ds-key"}},
        "video": {"api_key": "vid-key"},
    })
    with pytest.raises(EnvironmentError, match="dashscope.*api_url"):
        Config.from_settings()


def test_from_settings_defaults(monkeypatch):
    """Optional fields use defaults when not in TOML."""
    _patch_settings(monkeypatch, {
        "flask": {"secret_key": "s3cr3t", "port": 5005},
        "image": {
            "dashscope": {
                "api_url": "https://img.example.com/v1",
                "model": ["m"],
                "model_edit": ["m"],
            },
        },
        "video": {
            "api_url": "https://vid.example.com",
            "model_image": ["m"],
            "model_text": ["m"],
        },
    }, {
        "image": {"dashscope": {"api_key": "img-key"}},
        "video": {"api_key": "vid-key"},
    })
    cfg = Config.from_settings()
    assert cfg.image_backends["dashscope"].api_version == "2024-02-01"
    assert cfg.video_backend == "fal"
    assert cfg.video_api_version == "2025-04-01-preview"
    assert cfg.sd_api_url == ""
    assert cfg.sd_model == ""


def test_from_settings_real_toml_files(tmp_path, monkeypatch):
    """Write actual TOML files and verify end-to-end loading."""
    import config as cfg_module

    settings_file = tmp_path / "settings.toml"
    settings_file.write_text(
        '[flask]\n'
        'secret_key = "test-secret"\n'
        'port = 5005\n'
        '\n'
        '[image]\n'
        'default_backend = "fal"\n'
        '\n'
        '[image.fal]\n'
        'api_url = "https://img.example.com"\n'
        'model = ["model-a", "model-b"]\n'
        'model_edit = ["edit-model"]\n'
        '\n'
        '[video]\n'
        'backend = "fal"\n'
        'api_url = "https://vid.example.com"\n'
        'model_image = ["vid-img"]\n'
        'model_text = ["vid-txt"]\n'
    )
    secrets_file = tmp_path / ".secrets.toml"
    secrets_file.write_text(
        '[image.fal]\n'
        'api_key = "real-img-key"\n'
        '\n'
        '[video]\n'
        'api_key = "real-vid-key"\n'
    )

    merged = _merge(
        _load_toml(str(settings_file)),
        _load_toml(str(secrets_file)),
    )
    monkeypatch.setattr(cfg_module, "_settings", merged)

    cfg = Config.from_settings()
    assert cfg.image_backends["fal"].api_key == "real-img-key"
    assert cfg.video_api_key == "real-vid-key"
    assert cfg.image_backends["fal"].model == ["model-a", "model-b"]
    assert cfg.image_default_backend == "fal"
    assert cfg.secret_key == "test-secret"
