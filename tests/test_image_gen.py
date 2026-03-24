import base64
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

        result = generate_image(cfg, prompt="make it blue", image_bytes=b"jpeg-data")

        call_kwargs = instance.images.edit.call_args.kwargs
        assert call_kwargs["model"] == cfg.image_model_edit[0]
        assert result == FAKE_PNG


def test_image_to_image_uses_explicit_model_edit(cfg):
    """Explicit model_edit param overrides cfg default."""
    with patch("services.image_gen.OpenAI") as MockClient:
        instance = MockClient.return_value
        instance.images.edit.return_value = _make_mock_response(FAKE_B64)

        result = generate_image(
            cfg, prompt="make it blue", image_bytes=b"jpeg-data", model_edit="edit/model"
        )

        call_kwargs = instance.images.edit.call_args.kwargs
        assert call_kwargs["model"] == "edit/model"
        assert result == FAKE_PNG
