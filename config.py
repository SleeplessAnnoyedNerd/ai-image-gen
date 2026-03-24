import os
from dataclasses import dataclass


def _require(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise EnvironmentError(f"Required environment variable {name!r} is not set.")
    return val


def _parse_list(val: str) -> list[str]:
    """Split a comma-separated string into a stripped, non-empty list."""
    return [m.strip() for m in val.split(",") if m.strip()]


@dataclass
class Config:
    image_api_url: str
    image_api_key: str
    image_model: list[str]        # text-to-image models; first is default
    image_model_edit: list[str]   # image+prompt-to-image models; first is default
    image_backend: str            # "openai", "azure", or "fal"
    image_api_version: str        # Azure API version (only used for azure backend)
    video_backend: str            # "fal" or "azure"
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
    def from_env(cls) -> "Config":
        return cls(
            image_api_url=_require("IMAGE_API_URL"),
            image_api_key=_require("IMAGE_API_KEY"),
            image_model=_parse_list(_require("IMAGE_MODEL")),
            image_model_edit=_parse_list(_require("IMAGE_MODEL_EDIT")),
            image_backend=os.environ.get("IMAGE_BACKEND", "openai"),
            image_api_version=os.environ.get("IMAGE_API_VERSION", "2024-02-01"),
            video_backend=os.environ.get("VIDEO_BACKEND", "fal"),
            video_api_url=_require("VIDEO_API_URL"),
            video_api_key=_require("VIDEO_API_KEY"),
            video_api_version=os.environ.get("VIDEO_API_VERSION", "2025-04-01-preview"),
            video_azure_path=os.environ.get(
                "VIDEO_AZURE_PATH",
                "openai/deployments/{deployment}/videos/generations",
            ),
            video_model_image=_parse_list(_require("VIDEO_MODEL_IMAGE")),
            video_model_text=_parse_list(_require("VIDEO_MODEL_TEXT")),
            secret_key=_require("FLASK_SECRET_KEY"),
            sd_api_url=os.environ.get("SD_API_URL", ""),
            sd_model=os.environ.get("SD_MODEL", ""),
        )
