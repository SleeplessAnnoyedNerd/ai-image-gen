import pytest
from app import create_app
from config import Config, ImageBackend


@pytest.fixture
def cfg():
    return Config(
        image_backends={
            "openai": ImageBackend(
                name="openai",
                api_url="https://image.example.com/v1",
                api_key="test-image-key",
                model=["test/image-model"],
                model_edit=["test/image-edit-model"],
                api_version="2024-02-01",
            ),
        },
        image_default_backend="openai",
        video_backend="fal",
        video_api_url="https://video.example.com",
        video_api_key="test-video-key",
        video_api_version="2025-04-01-preview",
        video_azure_path="openai/deployments/{deployment}/videos/generations",
        video_model_image=["test/video-image-model"],
        video_model_text=["test/video-text-model"],
        secret_key="test-secret",
        sd_api_url="",
        sd_model="",
    )


@pytest.fixture
def app(cfg):
    application = create_app(cfg)
    application.config["TESTING"] = True
    return application


@pytest.fixture
def client(app):
    return app.test_client()
