from unittest.mock import patch, MagicMock
from services.sd_gen import generate_image_sd


def test_sd_accepts_images_list(cfg):
    """generate_image_sd accepts images: list[bytes] and extracts first."""
    mock_model = {"key": "m", "hash": "m", "name": "TestModel", "base": "sdxl", "type": "main"}

    with patch("services.sd_gen._get_model", return_value=mock_model), \
         patch("services.sd_gen._upload_image", return_value="img-name") as mock_upload, \
         patch("services.sd_gen._img2img_graph", return_value={"id": "g"}) as mock_graph, \
         patch("services.sd_gen._enqueue", return_value="batch-1"), \
         patch("services.sd_gen._wait_and_fetch", return_value=b"png-bytes"):
        result = generate_image_sd(cfg, prompt="test", images=[b"first-img", b"second-img"])

    assert result == b"png-bytes"
    mock_upload.assert_called_once_with(cfg.sd_api_url, b"first-img")


def test_sd_empty_images_uses_txt2img(cfg):
    """generate_image_sd with empty list uses txt2img path."""
    mock_model = {"key": "m", "hash": "m", "name": "TestModel", "base": "sdxl", "type": "main"}

    with patch("services.sd_gen._get_model", return_value=mock_model), \
         patch("services.sd_gen._txt2img_graph", return_value={"id": "g"}) as mock_txt2img, \
         patch("services.sd_gen._enqueue", return_value="batch-1"), \
         patch("services.sd_gen._wait_and_fetch", return_value=b"png-bytes"):
        result = generate_image_sd(cfg, prompt="test", images=[])

    assert result == b"png-bytes"
    mock_txt2img.assert_called_once()
