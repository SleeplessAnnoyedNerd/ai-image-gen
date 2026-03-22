import os
from dataclasses import dataclass


def _require(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise EnvironmentError(f"Required environment variable {name!r} is not set.")
    return val


@dataclass
class Config:
    image_api_url: str
    image_api_key: str
    image_model: str            # text-to-image model
    image_model_edit: str       # image+prompt-to-image model
    image_backend: str          # "openai" or "fal"
    video_api_url: str
    video_api_key: str
    video_model_image: str
    video_model_text: str
    secret_key: str
    sd_api_url: str             # InvokeAI base URL, e.g. http://localhost:9090 (empty = disabled)
    sd_model: str               # InvokeAI model name

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            image_api_url=_require("IMAGE_API_URL"),
            image_api_key=_require("IMAGE_API_KEY"),
            image_model=_require("IMAGE_MODEL"),
            image_model_edit=_require("IMAGE_MODEL_EDIT"),
            image_backend=os.environ.get("IMAGE_BACKEND", "openai"),
            video_api_url=_require("VIDEO_API_URL"),
            video_api_key=_require("VIDEO_API_KEY"),
            video_model_image=_require("VIDEO_MODEL_IMAGE"),
            video_model_text=_require("VIDEO_MODEL_TEXT"),
            secret_key=_require("FLASK_SECRET_KEY"),
            sd_api_url=os.environ.get("SD_API_URL", ""),
            sd_model=os.environ.get("SD_MODEL", ""),
        )
