import tomllib
from dataclasses import dataclass
from pathlib import Path

_BASE_DIR = Path(__file__).resolve().parent


def _load_toml(path: str) -> dict:
    p = _BASE_DIR / path
    if not p.exists():
        return {}
    with open(p, "rb") as f:
        return tomllib.load(f)


def _merge(base: dict, override: dict) -> dict:
    result = {**base}
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _merge(result[key], val)
        else:
            result[key] = val
    return result


_settings = _merge(_load_toml("settings.toml"), _load_toml(".secrets.toml"))


def _require(section: str, key: str):
    """Return raw value from _settings. Raises EnvironmentError if missing/empty."""
    try:
        val = _settings[section][key]
    except KeyError:
        raise EnvironmentError(f"Required config [{section}].{key} missing")
    if val is None:
        raise EnvironmentError(f"Required config [{section}].{key} is empty")
    if isinstance(val, str) and not val.strip():
        raise EnvironmentError(f"Required config [{section}].{key} is empty")
    return val


def _get(section: str, key: str, default=""):
    """Return raw value from _settings, or default if missing/None."""
    try:
        val = _settings[section][key]
    except KeyError:
        return default
    if val is None:
        return default
    return val


def _parse_list(val) -> list[str]:
    """Handle both TOML lists (list) and comma-separated strings."""
    if isinstance(val, list):
        return val
    return [m.strip() for m in str(val).split(",") if m.strip()]


@dataclass
class Config:
    image_api_url: str
    image_api_key: str
    image_model: list[str]        # text-to-image models; first is default
    image_model_edit: list[str]   # image+prompt-to-image models; first is default
    image_backend: str            # "openai", "azure", "fal", or "dashscope"
    image_api_version: str        # Azure API version (only used for azure backend)
    video_backend: str            # "fal", "azure", or "dashscope"
    video_api_url: str
    video_api_key: str
    video_api_version: str        # Azure API version (only used for azure backend)
    video_azure_path: str         # Azure path template
    video_model_image: list[str]  # image-to-video models; first is default
    video_model_text: list[str]   # text-to-video models; first is default
    secret_key: str
    sd_api_url: str               # InvokeAI base URL, empty = disabled
    sd_model: str                 # InvokeAI model name

    @classmethod
    def from_settings(cls) -> "Config":
        return cls(
            image_api_url = str(_require("image", "api_url")),
            image_api_key = str(_require("image", "api_key")),
            image_model = _parse_list(_require("image", "model")),
            image_model_edit = _parse_list(_require("image", "model_edit")),
            image_backend = str(_get("image", "backend", "openai")),
            image_api_version = str(_get("image", "api_version", "2024-02-01")),
            video_backend = str(_get("video", "backend", "fal")),
            video_api_url = str(_require("video", "api_url")),
            video_api_key = str(_require("video", "api_key")),
            video_api_version = str(_get("video", "api_version", "2025-04-01-preview")),
            video_azure_path = str(_get(
                "video", "azure_path",
                "openai/deployments/{deployment}/videos/generations",
            )),
            video_model_image = _parse_list(_require("video", "model_image")),
            video_model_text = _parse_list(_require("video", "model_text")),
            secret_key = str(_require("flask", "secret_key")),
            sd_api_url = str(_get("sd", "api_url", "")),
            sd_model = str(_get("sd", "model", "")),
        )
