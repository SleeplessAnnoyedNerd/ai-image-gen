import pytest
from app import create_app
from config import Config


@pytest.fixture
def cfg():
    return Config(
        image_api_url="https://image.example.com/v1",
        image_api_key="test-image-key",
        image_model="test/image-model",
        video_api_url="https://video.example.com",
        video_api_key="test-video-key",
        video_model_image="test/video-image-model",
        video_model_text="test/video-text-model",
        secret_key="test-secret",
    )


@pytest.fixture
def app(cfg):
    application = create_app(cfg)
    application.config["TESTING"] = True
    return application


@pytest.fixture
def client(app):
    return app.test_client()
