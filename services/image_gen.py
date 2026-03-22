import base64
import io
from openai import OpenAI
from config import Config


def generate_image(cfg: Config, prompt: str, image_bytes: bytes | None = None) -> bytes:
    client = OpenAI(api_key=cfg.image_api_key, base_url=cfg.image_api_url)

    if image_bytes is None:
        response = client.images.generate(
            model=cfg.image_model,
            prompt=prompt,
            response_format="b64_json",
            n=1,
        )
    else:
        response = client.images.edit(
            model=cfg.image_model,
            image=io.BytesIO(image_bytes),
            prompt=prompt,
            response_format="b64_json",
            n=1,
        )

    return base64.b64decode(response.data[0].b64_json)
