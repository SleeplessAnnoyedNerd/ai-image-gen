import base64
from unittest.mock import MagicMock, patch
from services.image_gen import generate_image


FAKE_PNG = b"\x89PNG\r\n\x1a\n"  # minimal PNG header bytes
FAKE_B64 = base64.b64encode(FAKE_PNG).decode()


def _make_mock_response(b64: str):
    img = MagicMock()
    img.b64_json = b64
    resp = MagicMock()
    resp.data = [img]
    return resp


def test_text_to_image(cfg):
    with patch("services.image_gen.OpenAI") as MockClient:
        instance = MockClient.return_value
        instance.images.generate.return_value = _make_mock_response(FAKE_B64)

        result = generate_image(cfg, prompt="a cat")

        MockClient.assert_called_once_with(
            api_key=cfg.image_api_key, base_url=cfg.image_api_url
        )
        instance.images.generate.assert_called_once()
        call_kwargs = instance.images.generate.call_args.kwargs
        assert call_kwargs["prompt"] == "a cat"
        assert call_kwargs["model"] == cfg.image_model
        assert result == FAKE_PNG


def test_image_to_image(cfg):
    with patch("services.image_gen.OpenAI") as MockClient:
        instance = MockClient.return_value
        instance.images.edit.return_value = _make_mock_response(FAKE_B64)

        result = generate_image(cfg, prompt="make it blue", image_bytes=b"jpeg-data")

        instance.images.edit.assert_called_once()
        call_kwargs = instance.images.edit.call_args.kwargs
        assert call_kwargs["prompt"] == "make it blue"
        assert result == FAKE_PNG
