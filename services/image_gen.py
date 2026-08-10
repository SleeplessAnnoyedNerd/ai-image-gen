import base64
import io
import requests as _requests
from loguru import logger
from openai import OpenAI, AzureOpenAI
from config import Config


def _mime_and_b64(img_bytes: bytes) -> str:
    """Return data URI string with best-effort MIME detection."""
    if ((len(img_bytes) >= 4) and (img_bytes[:4] == b'\x89PNG')):
        mime = "image/png"
    elif ((len(img_bytes) >= 3) and (img_bytes[:3] == b'\xff\xd8\xff')):
        mime = "image/jpeg"
    elif ((len(img_bytes) >= 12) and (img_bytes[:4] == b'RIFF') and (img_bytes[8:12] == b'WEBP')):
        mime = "image/webp"
    elif ((len(img_bytes) >= 6) and (img_bytes[:6] in (b'GIF87a', b'GIF89a'))):
        mime = "image/gif"
    else:
        mime = "application/octet-stream"
    b64 = base64.b64encode(img_bytes).decode()
    return f"data:{mime};base64,{b64}"


def generate_image(
    cfg: Config,
    prompt: str,
    image_bytes: bytes | None = None,
    model: str | None = None,
    model_edit: str | None = None,
) -> bytes:
    model = model or cfg.image_model[0]
    model_edit = model_edit or cfg.image_model_edit[0]
    if cfg.image_backend == "fal":
        return _generate_fal(cfg, prompt, image_bytes, model, model_edit)
    if cfg.image_backend == "azure":
        return _generate_azure(cfg, prompt, image_bytes, model, model_edit)
    if cfg.image_backend == "dashscope":
        return _generate_dashscope(cfg, prompt, image_bytes, model, model_edit)
    return _generate_openai(cfg, prompt, image_bytes, model, model_edit)


def _generate_azure(
    cfg: Config,
    prompt: str,
    image_bytes: bytes | None,
    model: str,
    model_edit: str,
) -> bytes:
    logger.info(
        "Azure config | endpoint={} api_version={} model={} model_edit={}",
        cfg.image_api_url, cfg.image_api_version, model, model_edit,
    )
    client = AzureOpenAI(
        api_key=cfg.image_api_key,
        azure_endpoint=cfg.image_api_url,
        api_version=cfg.image_api_version,
    )

    if image_bytes is None:
        logger.info("Generating image (azure) | model={} prompt={!r}", model, prompt)
        response = client.images.generate(model=model, prompt=prompt, n=1)
    else:
        logger.info("Editing image (azure) | model={} prompt={!r}", model_edit, prompt)
        mime = "image/png" if image_bytes[:4] == b'\x89PNG' else "image/jpeg"
        ext = "png" if mime == "image/png" else "jpg"
        response = client.images.edit(
            model=model_edit,
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


def _generate_openai(
    cfg: Config,
    prompt: str,
    image_bytes: bytes | None,
    model: str,
    model_edit: str,
) -> bytes:
    client = OpenAI(api_key=cfg.image_api_key, base_url=cfg.image_api_url)

    if image_bytes is None:
        logger.info("Generating image (openai) | model={} prompt={!r}", model, prompt)
        response = client.images.generate(
            model=model, prompt=prompt, response_format="b64_json", n=1,
        )
    else:
        logger.info("Editing image (openai) | model={} prompt={!r}", model_edit, prompt)
        response = client.images.edit(
            model=model_edit,
            image=io.BytesIO(image_bytes),
            prompt=prompt,
            response_format="b64_json",
            n=1,
        )

    result = base64.b64decode(response.data[0].b64_json)
    logger.info("Image generation complete | size={} bytes", len(result))
    return result


def _generate_fal(
    cfg: Config,
    prompt: str,
    image_bytes: bytes | None,
    model: str,
    model_edit: str,
) -> bytes:
    if image_bytes is not None:
        mime = "image/png" if image_bytes[:4] == b'\x89PNG' else "image/jpeg"
        img_b64 = base64.b64encode(image_bytes).decode()
        payload: dict = {
            "prompt": prompt,
            "image_urls": [f"data:{mime};base64,{img_b64}"],
        }
        active_model = model_edit
    else:
        payload = {"prompt": prompt}
        active_model = model

    url = f"{cfg.image_api_url.rstrip('/')}/{active_model}"
    headers = {
        "Authorization": f"Key {cfg.image_api_key}",
        "Content-Type": "application/json",
    }

    logger.info(
        "Generating image (fal) | url={} prompt={!r} has_image={}",
        url, prompt, image_bytes is not None,
    )
    resp = _requests.post(url, json=payload, headers=headers)
    resp.raise_for_status()

    result_url = resp.json()["images"][0]["url"]
    logger.info("Fetching generated image from {}", result_url)
    img_resp = _requests.get(result_url)
    img_resp.raise_for_status()

    logger.info("Image generation complete | size={} bytes", len(img_resp.content))
    return img_resp.content


def _generate_dashscope(
    cfg: Config,
    prompt: str,
    image_bytes: bytes | None,
    model: str,
    model_edit: str,
) -> bytes:
    if not cfg.image_api_url or not cfg.image_api_key:
        raise ValueError(
            "DashScope backend requires IMAGE_API_URL and IMAGE_API_KEY"
        )

    active_model = model_edit if image_bytes is not None else model
    url = cfg.image_api_url.rstrip("/")  # strip trailing slash to avoid double //

    content = [{"text": prompt}]
    if image_bytes is not None:
        mime = "image/png" if image_bytes[:4] == b'\x89PNG' else "image/jpeg"
        b64 = base64.b64encode(image_bytes).decode()
        content.append({"image": f"data:{mime};base64,{b64}"})

    payload = {
        "model": active_model,
        "input": {
            "messages": [{
                "role": "user",
                "content": content,
            }]
        },
        "parameters": {
            "size": "1K",
            "n": 1,
        },
    }

    headers = {
        "Authorization": f"Bearer {cfg.image_api_key}",
        "Content-Type": "application/json",
    }

    logger.info(
        "Generating image (dashscope) | model={} prompt={!r} has_image={}",
        active_model, prompt, image_bytes is not None,
    )
    resp = _requests.post(url, json=payload, headers=headers)
    if not resp.ok:
        logger.error("DashScope image API error | status={} body={}", resp.status_code, resp.text)
        _raise_dashscope_error(resp)

    data = resp.json()
    choices = data.get("output", {}).get("choices", [])
    if not choices:
        raise RuntimeError(f"DashScope returned no choices: {data}")

    content_list = choices[0].get("message", {}).get("content", [])
    image_url = None
    for item in content_list:
        if item.get("type") == "image":
            image_url = item.get("image")
            break

    if not image_url:
        raise RuntimeError(f"DashScope returned no image in response: {data}")

    logger.info("Fetching generated image from {}", image_url)
    img_resp = _requests.get(image_url)
    img_resp.raise_for_status()

    logger.info("DashScope image generation complete | size={} bytes", len(img_resp.content))
    return img_resp.content


def _raise_dashscope_error(resp):
    """Parse DashScope error response and raise with the message field."""
    try:
        body = resp.json()
        message = body.get("message", resp.text)
    except Exception:
        message = resp.text
    raise RuntimeError(f"DashScope error {resp.status_code}: {message}")
