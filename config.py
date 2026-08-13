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
    if isinstance(val, list) and not val:
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
class ImageBackend:
    name: str
    api_url: str
    api_key: str
    model: list[str]         # text-to-image models; first is default
    model_edit: list[str]    # image+prompt-to-image models; first is default
    api_version: str         # only read by the azure backend; defaults to "2024-02-01" for all backends


def _load_image_backends() -> tuple[dict[str, "ImageBackend"], str]:
    """Build an ImageBackend per [image.<name>] subtable with a non-empty api_key.
    Returns (backends dict, default_backend name)."""
    image_section = _settings.get("image", {})
    backends: dict[str, ImageBackend] = {}
    for name, val in image_section.items():
        if not isinstance(val, dict):
            continue  # scalar keys like default_backend
        api_key = str(val.get("api_key", "")).strip()
        if not api_key:
            continue  # unconfigured backend, hide from selection
        api_url = str(val.get("api_url", "")).strip()
        if not api_url:
            raise EnvironmentError(f"[image.{name}] has an api_key but is missing api_url")
        model = _parse_list(val.get("model", []))
        model_edit = _parse_list(val.get("model_edit", []))
        if not model or not model_edit:
            raise EnvironmentError(f"[image.{name}] has an api_key but is missing model/model_edit")
        backends[name] = ImageBackend(
            name=name,
            api_url=api_url,
            api_key=api_key,
            model=model,
            model_edit=model_edit,
            api_version=str(val.get("api_version", "2024-02-01")),
        )
    if not backends:
        raise EnvironmentError("No [image.*] backend configured with an api_key")

    default_backend = str(image_section.get("default_backend", ""))
    if default_backend not in backends:
        default_backend = next(iter(backends))
    return backends, default_backend


@dataclass
class Config:
    image_backends: dict[str, ImageBackend]  # keyed by backend name; only backends with a non-empty api_key
    image_default_backend: str               # key into image_backends
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
    prompt_min_use_count: int = 1  # default-list cutoff; search ignores it

    @classmethod
    def from_settings(cls) -> "Config":
        image_backends, image_default_backend = _load_image_backends()
        return cls(
            image_backends = image_backends,
            image_default_backend = image_default_backend,
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
            prompt_min_use_count = int(_get("prompts", "min_use_count", "1")),
        )


def resolve_data_dir() -> Path:
    """Absolute directory for everything the app writes.

    Anchored to the project root the same way the settings files are, so the
    app reads and writes the same place no matter where it was launched from.
    Pure: the caller creates the directory.
    """
    configured = str(_get("paths", "data_dir", ".")).strip()
    if (not configured):
        configured = "."
    return (_BASE_DIR / configured).resolve()
