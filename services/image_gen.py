import base64
import io
import requests as _requests
from loguru import logger
from openai import OpenAI, AzureOpenAI
from config import Config


def generate_image(cfg: Config, prompt: str, image_bytes: bytes | None = None) -> bytes:
    if cfg.image_backend == "fal":
        return _generate_fal(cfg, prompt, image_bytes)
    if cfg.image_backend == "azure":
        return _generate_azure(cfg, prompt, image_bytes)
    return _generate_openai(cfg, prompt, image_bytes)


def _generate_azure(cfg: Config, prompt: str, image_bytes: bytes | None) -> bytes:
    logger.info(
        "Azure config | endpoint={} api_version={} model={} model_edit={}",
        cfg.image_api_url, cfg.image_api_version, cfg.image_model, cfg.image_model_edit,
    )
    client = AzureOpenAI(
        api_key=cfg.image_api_key,
        azure_endpoint=cfg.image_api_url,
        api_version=cfg.image_api_version,
    )

    if image_bytes is None:
        logger.info("Generating image (azure) | model={} prompt={!r}", cfg.image_model, prompt)
        response = client.images.generate(
            model=cfg.image_model,
            prompt=prompt,
            n=1,
        )
    else:
        logger.info("Editing image (azure) | model={} prompt={!r}", cfg.image_model_edit, prompt)
        mime = "image/png" if image_bytes[:4] == b'\x89PNG' else "image/jpeg"
        ext = "png" if mime == "image/png" else "jpg"
        response = client.images.edit(
            model=cfg.image_model_edit,
            image=(f"image.{ext}", io.BytesIO(image_bytes), mime),
            prompt=prompt,
            n=1,
        )

    item = response.data[0]
    if item.b64_json:
        result = base64.b64decode(item.b64_json)
    else:
        img_resp = _requests.get(item.url)
        img_resp.raise_for_status()
        result = img_resp.content
    logger.info("Azure image generation complete | size={} bytes", len(result))
    return result


def _generate_openai(cfg: Config, prompt: str, image_bytes: bytes | None) -> bytes:
    client = OpenAI(api_key=cfg.image_api_key, base_url=cfg.image_api_url)

    if image_bytes is None:
        logger.info("Generating image (openai) | model={} prompt={!r}", cfg.image_model, prompt)
        response = client.images.generate(
            model=cfg.image_model,
            prompt=prompt,
            response_format="b64_json",
            n=1,
        )
    else:
        logger.info("Editing image (openai) | model={} prompt={!r}", cfg.image_model, prompt)
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


def _generate_fal(cfg: Config, prompt: str, image_bytes: bytes | None) -> bytes:
    if image_bytes is not None:
        model = cfg.image_model_edit
        img_b64 = base64.b64encode(image_bytes).decode()
        payload: dict = {
            "prompt": prompt,
            "image_urls": [f"data:image/jpeg;base64,{img_b64}"],
        }
    else:
        model = cfg.image_model
        payload = {"prompt": prompt}

    url = f"{cfg.image_api_url.rstrip('/')}/{model}"
    headers = {
        "Authorization": f"Key {cfg.image_api_key}",
        "Content-Type": "application/json",
    }

    logger.info("Generating image (fal) | url={} prompt={!r} has_image={}", url, prompt, image_bytes is not None)
    resp = _requests.post(url, json=payload, headers=headers)
    resp.raise_for_status()

    result_url = resp.json()["images"][0]["url"]
    logger.info("Fetching generated image from {}", result_url)
    img_resp = _requests.get(result_url)
    img_resp.raise_for_status()

    logger.info("Image generation complete | size={} bytes", len(img_resp.content))
    return img_resp.content
