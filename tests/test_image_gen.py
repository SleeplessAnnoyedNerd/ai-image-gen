import base64
import pytest
from unittest.mock import MagicMock, patch
from services.image_gen import generate_image


FAKE_PNG = b"\x89PNG\r\n\x1a\n"
FAKE_B64 = base64.b64encode(FAKE_PNG).decode()


def _make_mock_response(b64: str):
    img = MagicMock()
    img.b64_json = b64
    resp = MagicMock()
    resp.data = [img]
    return resp


def test_text_to_image_uses_cfg_default(cfg):
    """When no model param passed, use cfg.image_model[0]."""
    with patch("services.image_gen.OpenAI") as MockClient:
        instance = MockClient.return_value
        instance.images.generate.return_value = _make_mock_response(FAKE_B64)

        result = generate_image(cfg, prompt="a cat")

        call_kwargs = instance.images.generate.call_args.kwargs
        assert call_kwargs["model"] == cfg.image_model[0]
        assert result == FAKE_PNG


def test_text_to_image_uses_explicit_model(cfg):
    """Explicit model param overrides cfg default."""
    with patch("services.image_gen.OpenAI") as MockClient:
        instance = MockClient.return_value
        instance.images.generate.return_value = _make_mock_response(FAKE_B64)

        result = generate_image(cfg, prompt="a cat", model="custom/model")

        call_kwargs = instance.images.generate.call_args.kwargs
        assert call_kwargs["model"] == "custom/model"
        assert result == FAKE_PNG


def test_image_to_image_uses_cfg_edit_default(cfg):
    """When no model_edit param passed, use cfg.image_model_edit[0]."""
    with patch("services.image_gen.OpenAI") as MockClient:
        instance = MockClient.return_value
        instance.images.edit.return_value = _make_mock_response(FAKE_B64)

        result = generate_image(cfg, prompt="make it blue", images=[b"jpeg-data"])

        call_kwargs = instance.images.edit.call_args.kwargs
        assert call_kwargs["model"] == cfg.image_model_edit[0]
        assert result == FAKE_PNG


def test_image_to_image_uses_explicit_model_edit(cfg):
    """Explicit model_edit param overrides cfg default."""
    with patch("services.image_gen.OpenAI") as MockClient:
        instance = MockClient.return_value
        instance.images.edit.return_value = _make_mock_response(FAKE_B64)

        result = generate_image(
            cfg, prompt="make it blue", images=[b"jpeg-data"], model_edit="edit/model"
        )

        call_kwargs = instance.images.edit.call_args.kwargs
        assert call_kwargs["model"] == "edit/model"
        assert result == FAKE_PNG


# --- DashScope backend tests ---

from config import Config


def _dashscope_cfg():
    """Helper to create a Config with dashscope backend."""
    return Config(
        image_api_url="https://ws-c2xbh4slyhwu4ifn.ap-southeast-1.maas.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
        image_api_key="sk-test-key",
        image_model=["wan2.7-image"], image_model_edit=["wan2.7-image-pro"],
        image_backend="dashscope", image_api_version="",
        video_backend="fal", video_api_url="", video_api_key="",
        video_api_version="", video_azure_path="",
        video_model_image=[""], video_model_text=[""],
        secret_key="test", sd_api_url="", sd_model="",
    )


def test_dashscope_text_to_image():
    """DashScope backend: text-only prompt generates image."""
    cfg = _dashscope_cfg()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "output": {
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "content": [
                        {"type": "image", "image": "https://cdn.example.com/img.png"}
                    ]
                }
            }]
        },
        "request_id": "req-123",
    }
    mock_response.raise_for_status = MagicMock()

    mock_img_resp = MagicMock()
    mock_img_resp.content = FAKE_PNG
    mock_img_resp.raise_for_status = MagicMock()

    with patch("services.image_gen._requests.post", return_value=mock_response), \
         patch("services.image_gen._requests.get", return_value=mock_img_resp):
        result = generate_image(cfg, prompt="a cat wearing a hat")

    assert result == FAKE_PNG


def test_dashscope_image_to_image():
    """DashScope backend: prompt + reference image generates edited image."""
    cfg = _dashscope_cfg()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "output": {
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "content": [
                        {"type": "image", "image": "https://cdn.example.com/img.png"}
                    ]
                }
            }]
        },
        "request_id": "req-456",
    }
    mock_response.raise_for_status = MagicMock()

    mock_img_resp = MagicMock()
    mock_img_resp.content = FAKE_PNG
    mock_img_resp.raise_for_status = MagicMock()

    with patch("services.image_gen._requests.post", return_value=mock_response) as mock_post, \
         patch("services.image_gen._requests.get", return_value=mock_img_resp):
        result = generate_image(cfg, prompt="make it blue", images=[FAKE_PNG])

    assert result == FAKE_PNG

    # Verify the request included the image in the messages content
    payload = mock_post.call_args.kwargs["json"]
    content = payload["input"]["messages"][0]["content"]
    assert len(content) == 2
    assert content[0] == {"text": "make it blue"}
    assert content[1]["image"].startswith("data:image/png;base64,")


def test_dashscope_missing_config_raises():
    """DashScope backend: raises ValueError when api_url is empty."""
    cfg = Config(
        image_api_url="", image_api_key="",
        image_model=["wan2.7-image"], image_model_edit=["wan2.7-image-pro"],
        image_backend="dashscope", image_api_version="",
        video_backend="fal", video_api_url="", video_api_key="",
        video_api_version="", video_azure_path="",
        video_model_image=[""], video_model_text=[""],
        secret_key="test", sd_api_url="", sd_model="",
    )
    with pytest.raises(ValueError, match="IMAGE_API_URL"):
        generate_image(cfg, prompt="a cat")


# --- _mime_and_b64 tests ---

from services.image_gen import _mime_and_b64


def test_mime_and_b64_png():
    result = _mime_and_b64(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
    assert result.startswith("data:image/png;base64,")


def test_mime_and_b64_jpeg():
    result = _mime_and_b64(b"\xff\xd8\xff\xe0" + b"\x00" * 100)
    assert result.startswith("data:image/jpeg;base64,")


def test_mime_and_b64_webp():
    data = b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 100
    result = _mime_and_b64(data)
    assert result.startswith("data:image/webp;base64,")


def test_mime_and_b64_gif():
    result = _mime_and_b64(b"GIF89a" + b"\x00" * 100)
    assert result.startswith("data:image/gif;base64,")


def test_mime_and_b64_unknown():
    result = _mime_and_b64(b"\x00\x01\x02\x03")
    assert result.startswith("data:application/octet-stream;base64,")


def test_mime_and_b64_tiny_file():
    """Files smaller than 4 bytes must not crash."""
    result = _mime_and_b64(b"\x89")
    assert result.startswith("data:application/octet-stream;base64,")


def test_mime_and_b64_empty():
    result = _mime_and_b64(b"")
    assert result.startswith("data:application/octet-stream;base64,")


# --- Multi-image tests ---


def test_dashscope_multi_image_payload():
    """DashScope: 3 images produce 3 image entries in the payload."""
    cfg = _dashscope_cfg()
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
    jpg = b"\xff\xd8\xff\xe0" + b"\x00" * 50
    png2 = b"\x89PNG\r\n\x1a\n" + b"\xff" * 50

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "output": {
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "content": [{"type": "image", "image": "https://cdn.example.com/img.png"}]
                }
            }]
        },
        "request_id": "req-multi",
    }
    mock_response.raise_for_status = MagicMock()

    mock_img_resp = MagicMock()
    mock_img_resp.content = FAKE_PNG
    mock_img_resp.raise_for_status = MagicMock()

    with patch("services.image_gen._requests.post", return_value=mock_response) as mock_post, \
         patch("services.image_gen._requests.get", return_value=mock_img_resp):
        generate_image(cfg, prompt="blend these", images=[png, jpg, png2])

    payload = mock_post.call_args.kwargs["json"]
    content = payload["input"]["messages"][0]["content"]
    assert len(content) == 4  # 1 text + 3 images
    assert content[0] == {"text": "blend these"}
    assert content[1]["image"].startswith("data:image/png;base64,")
    assert content[2]["image"].startswith("data:image/jpeg;base64,")
    assert content[3]["image"].startswith("data:image/png;base64,")


def test_dashscope_zero_images_uses_text_model():
    """DashScope: empty images list uses text model, no image entries."""
    cfg = _dashscope_cfg()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "output": {
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "content": [{"type": "image", "image": "https://cdn.example.com/img.png"}]
                }
            }]
        },
        "request_id": "req-zero",
    }
    mock_response.raise_for_status = MagicMock()

    mock_img_resp = MagicMock()
    mock_img_resp.content = FAKE_PNG
    mock_img_resp.raise_for_status = MagicMock()

    with patch("services.image_gen._requests.post", return_value=mock_response) as mock_post, \
         patch("services.image_gen._requests.get", return_value=mock_img_resp):
        generate_image(cfg, prompt="a cat", images=[])

    payload = mock_post.call_args.kwargs["json"]
    assert payload["model"] == cfg.image_model[0]  # text model, not edit
    content = payload["input"]["messages"][0]["content"]
    assert len(content) == 1  # text only
    assert content[0] == {"text": "a cat"}


def test_dashscope_ten_images():
    """DashScope: 10 images produce 10 entries (boundary test)."""
    cfg = _dashscope_cfg()
    imgs = [b"\x89PNG\r\n\x1a\n" + bytes([i]) * 50 for i in range(10)]

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "output": {
            "choices": [{
                "finish_reason": "stop",
                "message": {
                    "content": [{"type": "image", "image": "https://cdn.example.com/img.png"}]
                }
            }]
        },
        "request_id": "req-ten",
    }
    mock_response.raise_for_status = MagicMock()

    mock_img_resp = MagicMock()
    mock_img_resp.content = FAKE_PNG
    mock_img_resp.raise_for_status = MagicMock()

    with patch("services.image_gen._requests.post", return_value=mock_response) as mock_post, \
         patch("services.image_gen._requests.get", return_value=mock_img_resp):
        generate_image(cfg, prompt="many refs", images=imgs)

    payload = mock_post.call_args.kwargs["json"]
    content = payload["input"]["messages"][0]["content"]
    assert len(content) == 11  # 1 text + 10 images


def test_non_dashscope_receives_first_image_only():
    """OpenAI backend: only images[0] is passed when multiple provided."""
    cfg_openai = Config(
        image_api_url="https://api.openai.com/v1",
        image_api_key="sk-test",
        image_model=["dall-e-3"], image_model_edit=["gpt-image-1"],
        image_backend="openai", image_api_version="",
        video_backend="fal", video_api_url="", video_api_key="",
        video_api_version="", video_azure_path="",
        video_model_image=[""], video_model_text=[""],
        secret_key="test", sd_api_url="", sd_model="",
    )

    with patch("services.image_gen.OpenAI") as MockClient:
        instance = MockClient.return_value
        instance.images.edit.return_value = _make_mock_response(FAKE_B64)

        generate_image(cfg_openai, prompt="edit", images=[b"first-img", b"second-img", b"third-img"])

        call_kwargs = instance.images.edit.call_args.kwargs
        # The image param should be a BytesIO with only the first image's bytes
        img_io = call_kwargs["image"]
        assert img_io.read() == b"first-img"
