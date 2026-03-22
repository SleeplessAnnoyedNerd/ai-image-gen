import base64
import io
from loguru import logger
from openai import OpenAI
from config import Config


def generate_image(cfg: Config, prompt: str, image_bytes: bytes | None = None) -> bytes:
    client = OpenAI(api_key=cfg.image_api_key, base_url=cfg.image_api_url)

    if image_bytes is None:
        logger.info("Generating image from text | model={} prompt={!r}", cfg.image_model, prompt)
        response = client.images.generate(
            model=cfg.image_model,
            prompt=prompt,
            response_format="b64_json",
            n=1,
        )
    else:
        logger.info("Editing image | model={} prompt={!r}", cfg.image_model, prompt)
        response = client.images.edit(
            model=cfg.image_model,
            image=io.BytesIO(image_bytes),
            prompt=prompt,
            response_format="b64_json",
            n=1,
        )

    result = base64.b64decode(response.data[0].b64_json)
    logger.info("Image generation complete | size={} bytes", len(result))
    return result
