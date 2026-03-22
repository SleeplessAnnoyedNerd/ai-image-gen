import random
import time
import requests
from loguru import logger
from config import Config

_SD1_SIZE = 512
_SDXL_SIZE = 1024


def generate_image_sd(cfg: Config, prompt: str, image_bytes: bytes | None) -> bytes:
    model = _get_model(cfg.sd_api_url, cfg.sd_model)
    base = model.get("base", "sd-1")
    size = _SDXL_SIZE if base == "sdxl" else _SD1_SIZE
    logger.info("SD generation | model={} base={} has_image={}", model["name"], base, image_bytes is not None)

    if image_bytes is not None:
        image_name = _upload_image(cfg.sd_api_url, image_bytes)
        graph = _img2img_graph(model, prompt, image_name, size)
    else:
        graph = _txt2img_graph(model, prompt, size)

    batch_id = _enqueue(cfg.sd_api_url, graph)
    return _wait_and_fetch(cfg.sd_api_url, batch_id)


# ------------------------------------------------------------------ #
# InvokeAI API helpers                                                 #
# ------------------------------------------------------------------ #

def _get_model(base_url: str, model_name: str) -> dict:
    resp = requests.get(f"{base_url}/api/v2/models/", params={"model_type": "main"})
    resp.raise_for_status()
    models = resp.json().get("models", [])
    for m in models:
        if m.get("name") == model_name:
            return m
    names = [m.get("name") for m in models]
    raise ValueError(f"InvokeAI model {model_name!r} not found. Available: {names}")


def _upload_image(base_url: str, image_bytes: bytes) -> str:
    resp = requests.post(
        f"{base_url}/api/v1/images/upload",
        params={"image_category": "user", "is_intermediate": True},
        files={"file": ("image.jpg", image_bytes, "image/jpeg")},
    )
    resp.raise_for_status()
    image_name = resp.json()["image_name"]
    logger.info("Uploaded image to InvokeAI | name={}", image_name)
    return image_name


def _enqueue(base_url: str, graph: dict) -> str:
    resp = requests.post(
        f"{base_url}/api/v1/queue/default/enqueue_batch",
        json={"prepend": False, "batch": {"graph": graph, "runs": 1}},
    )
    if not resp.ok:
        logger.error("InvokeAI enqueue failed | status={} body={}", resp.status_code, resp.text)
    resp.raise_for_status()
    body = resp.json()
    logger.info("InvokeAI enqueue response | body={}", body)
    batch_id = body.get("batch_id") or body.get("batch", {}).get("batch_id")
    if not batch_id:
        raise RuntimeError(f"Could not find batch_id in enqueue response: {body}")
    logger.info("Enqueued SD batch | batch_id={}", batch_id)
    return batch_id


def _wait_and_fetch(base_url: str, batch_id: str, timeout: int = 300) -> bytes:
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(2)
        resp = requests.get(f"{base_url}/api/v1/queue/default/b/{batch_id}/status")
        resp.raise_for_status()
        s = resp.json()
        logger.debug("SD batch status | batch_id={} {}", batch_id, s)
        if s.get("failed", 0) > 0:
            raise RuntimeError("InvokeAI generation failed")
        if s.get("completed", 0) >= s.get("total", 1) and s.get("total", 0) > 0:
            break
    else:
        raise TimeoutError("InvokeAI generation timed out")

    resp = requests.get(
        f"{base_url}/api/v1/images/",
        params={"batch_id": batch_id, "is_intermediate": False},
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    if not items:
        raise RuntimeError("InvokeAI returned no images for batch")
    item = items[0]
    image_url = f"{base_url}/{item['image_url']}"
    logger.info("Fetching SD result image | url={}", image_url)

    img_resp = requests.get(image_url)
    img_resp.raise_for_status()
    return img_resp.content


# ------------------------------------------------------------------ #
# Node graph builders                                                  #
# ------------------------------------------------------------------ #

def _e(src_node, src_field, dst_node, dst_field) -> dict:
    return {
        "source":      {"node_id": src_node, "field": src_field},
        "destination": {"node_id": dst_node, "field": dst_field},
    }


def _model_ref(model: dict) -> dict:
    """Full model identifier as InvokeAI v4 requires."""
    return {
        "key":  model["key"],
        "hash": model.get("hash", model["key"]),
        "name": model["name"],
        "base": model["base"],
        "type": model.get("type", "main"),
    }


def _txt2img_graph(model: dict, prompt: str, size: int) -> dict:
    seed = random.randint(0, 2**31 - 1)
    ref = _model_ref(model)
    if model.get("base") == "sdxl":
        return _sdxl_txt2img(ref, prompt, seed, size)
    return _sd1_txt2img(ref, prompt, seed, size)


def _img2img_graph(model: dict, prompt: str, image_name: str, size: int) -> dict:
    seed = random.randint(0, 2**31 - 1)
    ref = _model_ref(model)
    if model.get("base") == "sdxl":
        return _sdxl_img2img(ref, prompt, image_name, seed, size)
    return _sd1_img2img(ref, prompt, image_name, seed, size)


def _sd1_txt2img(model_ref: dict, prompt: str, seed: int, size: int) -> dict:
    nodes = {
        "loader":    {"type": "main_model_loader", "id": "loader",    "model": model_ref},
        "clip_skip": {"type": "clip_skip",          "id": "clip_skip", "skipped_layers": 0},
        "pos":       {"type": "compel",             "id": "pos",       "prompt": prompt},
        "neg":       {"type": "compel",             "id": "neg",       "prompt": ""},
        "noise":     {"type": "noise",              "id": "noise",     "seed": seed, "width": size, "height": size, "use_cpu": False},
        "denoise":   {"type": "denoise_latents",    "id": "denoise",
                      "cfg_scale": 7.5, "steps": 30, "scheduler": "dpmpp_2m",
                      "denoising_start": 0.0, "denoising_end": 1.0},
        "decode":    {"type": "l2i",                "id": "decode",    "fp32": False},
        "save":      {"type": "save_image",         "id": "save",      "is_intermediate": False, "use_cache": False},
    }
    edges = [
        _e("loader",    "unet",         "denoise",   "unet"),
        _e("loader",    "vae",          "decode",    "vae"),
        _e("loader",    "clip",         "clip_skip", "clip"),
        _e("clip_skip", "clip",         "pos",       "clip"),
        _e("clip_skip", "clip",         "neg",       "clip"),
        _e("pos",       "conditioning", "denoise",   "positive_conditioning"),
        _e("neg",       "conditioning", "denoise",   "negative_conditioning"),
        _e("noise",     "noise",        "denoise",   "noise"),
        _e("denoise",   "latents",      "decode",    "latents"),
        _e("decode",    "image",        "save",      "image"),
    ]
    return {"id": "sd1_txt2img", "nodes": nodes, "edges": edges}


def _sd1_img2img(model_ref: dict, prompt: str, image_name: str, seed: int, size: int) -> dict:
    nodes = {
        "loader":    {"type": "main_model_loader", "id": "loader",    "model": model_ref},
        "clip_skip": {"type": "clip_skip",          "id": "clip_skip", "skipped_layers": 0},
        "pos":       {"type": "compel",             "id": "pos",       "prompt": prompt},
        "neg":       {"type": "compel",             "id": "neg",       "prompt": ""},
        "img_val":   {"type": "image",               "id": "img_val",   "image": {"image_name": image_name}},
        "resize":    {"type": "img_resize",         "id": "resize",    "width": size, "height": size, "resample_mode": "bicubic"},
        "encode":    {"type": "i2l",                "id": "encode",    "fp32": False, "tiled": False},
        "noise":     {"type": "noise",              "id": "noise",     "seed": seed, "width": size, "height": size, "use_cpu": False},
        "denoise":   {"type": "denoise_latents",    "id": "denoise",
                      "cfg_scale": 7.5, "steps": 30, "scheduler": "dpmpp_2m",
                      "denoising_start": 0.6, "denoising_end": 1.0},
        "decode":    {"type": "l2i",                "id": "decode",    "fp32": False},
        "save":      {"type": "save_image",         "id": "save",      "is_intermediate": False, "use_cache": False},
    }
    edges = [
        _e("loader",    "unet",         "denoise",   "unet"),
        _e("loader",    "vae",          "encode",    "vae"),
        _e("loader",    "vae",          "decode",    "vae"),
        _e("loader",    "clip",         "clip_skip", "clip"),
        _e("clip_skip", "clip",         "pos",       "clip"),
        _e("clip_skip", "clip",         "neg",       "clip"),
        _e("pos",       "conditioning", "denoise",   "positive_conditioning"),
        _e("neg",       "conditioning", "denoise",   "negative_conditioning"),
        _e("img_val",   "image",        "resize",    "image"),
        _e("resize",    "image",        "encode",    "image"),
        _e("encode",    "latents",      "denoise",   "latents"),
        _e("noise",     "noise",        "denoise",   "noise"),
        _e("denoise",   "latents",      "decode",    "latents"),
        _e("decode",    "image",        "save",      "image"),
    ]
    return {"id": "sd1_img2img", "nodes": nodes, "edges": edges}


def _sdxl_txt2img(model_ref: dict, prompt: str, seed: int, size: int) -> dict:
    nodes = {
        "loader": {"type": "sdxl_model_loader", "id": "loader", "model": model_ref},
        "pos":    {"type": "sdxl_compel_prompt", "id": "pos", "prompt": prompt, "style_prompt": prompt},
        "neg":    {"type": "sdxl_compel_prompt", "id": "neg", "prompt": "",     "style_prompt": ""},
        "noise":  {"type": "noise",              "id": "noise", "seed": seed, "width": size, "height": size, "use_cpu": False},
        "denoise":{"type": "denoise_latents",    "id": "denoise",
                   "cfg_scale": 7, "steps": 30, "scheduler": "dpmpp_2m",
                   "denoising_start": 0.0, "denoising_end": 1.0},
        "decode": {"type": "l2i",                "id": "decode", "fp32": False},
        "save":   {"type": "save_image",         "id": "save",   "is_intermediate": False, "use_cache": False},
    }
    edges = [
        _e("loader", "unet",         "denoise", "unet"),
        _e("loader", "vae",          "decode",  "vae"),
        _e("loader", "clip",         "pos",     "clip"),
        _e("loader", "clip2",        "pos",     "clip2"),
        _e("loader", "clip",         "neg",     "clip"),
        _e("loader", "clip2",        "neg",     "clip2"),
        _e("pos",    "conditioning", "denoise", "positive_conditioning"),
        _e("neg",    "conditioning", "denoise", "negative_conditioning"),
        _e("noise",  "noise",        "denoise", "noise"),
        _e("denoise","latents",      "decode",  "latents"),
        _e("decode", "image",        "save",    "image"),
    ]
    return {"id": "sdxl_txt2img", "nodes": nodes, "edges": edges}


def _sdxl_img2img(model_ref: dict, prompt: str, image_name: str, seed: int, size: int) -> dict:
    nodes = {
        "loader":  {"type": "sdxl_model_loader", "id": "loader",  "model": model_ref},
        "pos":     {"type": "sdxl_compel_prompt", "id": "pos",     "prompt": prompt, "style_prompt": prompt},
        "neg":     {"type": "sdxl_compel_prompt", "id": "neg",     "prompt": "",     "style_prompt": ""},
        "img_val": {"type": "image",               "id": "img_val", "image": {"image_name": image_name}},
        "resize":  {"type": "img_resize",         "id": "resize",  "width": size, "height": size, "resample_mode": "bicubic"},
        "encode":  {"type": "i2l",                "id": "encode",  "fp32": False, "tiled": False},
        "noise":   {"type": "noise",              "id": "noise",   "seed": seed, "width": size, "height": size, "use_cpu": False},
        "denoise": {"type": "denoise_latents",    "id": "denoise",
                    "cfg_scale": 7, "steps": 30, "scheduler": "dpmpp_2m",
                    "denoising_start": 0.3, "denoising_end": 1.0},
        "decode":  {"type": "l2i",                "id": "decode",  "fp32": False},
        "save":    {"type": "save_image",         "id": "save",    "is_intermediate": False, "use_cache": False},
    }
    edges = [
        _e("loader",  "unet",         "denoise", "unet"),
        _e("loader",  "vae",          "encode",  "vae"),
        _e("loader",  "vae",          "decode",  "vae"),
        _e("loader",  "clip",         "pos",     "clip"),
        _e("loader",  "clip2",        "pos",     "clip2"),
        _e("loader",  "clip",         "neg",     "clip"),
        _e("loader",  "clip2",        "neg",     "clip2"),
        _e("pos",     "conditioning", "denoise", "positive_conditioning"),
        _e("neg",     "conditioning", "denoise", "negative_conditioning"),
        _e("img_val", "image",        "resize",  "image"),
        _e("resize",  "image",        "encode",  "image"),
        _e("encode",  "latents",      "denoise", "latents"),
        _e("noise",   "noise",        "denoise", "noise"),
        _e("denoise", "latents",      "decode",  "latents"),
        _e("decode",  "image",        "save",    "image"),
    ]
    return {"id": "sdxl_img2img", "nodes": nodes, "edges": edges}
