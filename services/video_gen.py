import requests
from pathlib import Path
from urllib.parse import urlparse
from loguru import logger
from config import Config
from services.image_gen import _mime_and_b64
from services.model_specs import VideoSpec, video_spec


def start_video_job(
    cfg: Config,
    prompt: str,
    images: list[bytes] | None = None,
    model: str | None = None,
    duration: int | str | None = None,
    resolution: str | None = None,
    ratio: str | None = None,
) -> dict:
    """Submit a video generation job. Returns a submit-context dict for poll_video_job."""
    images = images or []
    model = model or cfg.video_model[0]
    first = images[0] if images else None
    if cfg.video_backend == "azure":
        return _start_azure(cfg, prompt, first, model)
    if cfg.video_backend == "dashscope":
        return _start_dashscope(cfg, prompt, images, model, duration, resolution, ratio)
    if cfg.video_backend == "dummy":
        return _start_dummy()
    return _start_fal(cfg, prompt, first, model)


def poll_video_job(cfg: Config, submit: dict) -> dict:
    """Poll a previously submitted job.
    Keys: status ("pending"|"done"|"error"), queue_position (int|None),
          video_data (bytes), message (str on error).
    """
    if cfg.video_backend == "azure":
        return _poll_azure(cfg, submit)
    if cfg.video_backend == "dashscope":
        return _poll_dashscope(cfg, submit)
    if cfg.video_backend == "dummy":
        return _poll_dummy(submit)
    return _poll_fal(cfg, submit)


# ------------------------------------------------------------------ #
# fal.ai backend                                                       #
# ------------------------------------------------------------------ #

def _start_fal(
    cfg: Config,
    prompt: str,
    image_bytes: bytes | None,
    model: str,
) -> dict:
    if image_bytes:
        data_uri = _mime_and_b64(image_bytes)
        payload = {
            "prompt": prompt,
            "image_url": data_uri,
        }
    else:
        payload = {"prompt": prompt}

    url = f"{cfg.video_api_url}/{model}"
    headers = {"Authorization": f"Key {cfg.video_api_key}", "Content-Type": "application/json"}
    logger.info(
        "Submitting fal video job | model={} prompt={!r} has_image={}",
        model, prompt, image_bytes is not None,
    )
    resp = requests.post(url, json=payload, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    logger.info("fal video job submitted | request_id={}", data.get("request_id"))
    return data


def _poll_fal(cfg: Config, submit: dict) -> dict:
    status_url = submit["status_url"]
    response_url = submit["response_url"]
    headers = {"Authorization": f"Key {cfg.video_api_key}"}

    resp = requests.get(status_url, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    status = data.get("status")

    if status == "COMPLETED":
        result = requests.get(response_url, headers=headers)
        result.raise_for_status()
        video_url = result.json()["video"]["url"]
        logger.info("fal video job complete | url={}", video_url)
        video_resp = requests.get(video_url)
        video_resp.raise_for_status()
        logger.info("fal video fetched | size={} bytes", len(video_resp.content))
        return {"status": "done", "video_data": video_resp.content}
    elif status == "FAILED":
        logger.error("fal video job failed | status_url={}", status_url)
        return {"status": "error", "message": "Video generation failed"}
    elif status == "IN_PROGRESS":
        return {"status": "pending", "queue_position": None}
    else:
        queue_position = data.get("queue_position")
        return {"status": "pending", "queue_position": queue_position}


# ------------------------------------------------------------------ #
# Azure OpenAI Sora backend                                            #
# ------------------------------------------------------------------ #

def _start_azure(
    cfg: Config,
    prompt: str,
    image_bytes: bytes | None,
    model: str,
) -> dict:
    deployment = model
    base = cfg.video_api_url.rstrip("/")
    path = cfg.video_azure_path.format(deployment=deployment)
    url = f"{base}/{path}?api-version={cfg.video_api_version}"
    logger.info("Azure Sora submit URL | {}", url)
    headers = {"api-key": cfg.video_api_key, "Content-Type": "application/json"}

    payload: dict = {
        "prompt": prompt,
        "n_seconds": 5,
        "width": 480,
        "height": 480,
        "n_variants": 1,
    }
    if image_bytes:
        payload["first_frame_image"] = _mime_and_b64(image_bytes)

    logger.info(
        "Submitting Azure Sora job | deployment={} prompt={!r} has_image={}",
        deployment, prompt, image_bytes is not None,
    )
    resp = requests.post(url, json=payload, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    job_id = data["id"]
    job_url = f"{base}/{path}/{job_id}?api-version={cfg.video_api_version}"
    logger.info("Azure Sora job submitted | job_id={}", job_id)
    return {"azure_job_url": job_url, "azure_deployment": deployment}


def _poll_azure(cfg: Config, submit: dict) -> dict:
    job_url = submit["azure_job_url"]
    headers = {"api-key": cfg.video_api_key}

    resp = requests.get(job_url, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    status = data.get("status")
    logger.debug("Azure Sora poll | status={}", status)

    if status == "succeeded":
        generations = data.get("generations", [])
        if generations and generations[0].get("video", {}).get("url"):
            video_url = generations[0]["video"]["url"]
            video_resp = requests.get(video_url, headers=headers)
            video_resp.raise_for_status()
        else:
            base_url = job_url.split("?")[0]
            version = cfg.video_api_version
            video_resp = requests.get(
                f"{base_url}/content/video?api-version={version}", headers=headers
            )
            video_resp.raise_for_status()
        logger.info("Azure Sora job complete | size={} bytes", len(video_resp.content))
        return {"status": "done", "video_data": video_resp.content}
    elif status == "failed":
        logger.error("Azure Sora job failed | job_url={}", job_url)
        return {"status": "error", "message": "Azure video generation failed"}
    else:
        return {"status": "pending", "queue_position": None}


# ------------------------------------------------------------------ #
# DashScope (Alibaba Cloud) backend                                    #
# ------------------------------------------------------------------ #

def _start_dashscope(
    cfg: Config,
    prompt: str,
    images: list[bytes],
    model: str,
    duration: int | str | None,
    resolution: str | None,
    ratio: str | None,
) -> dict:
    if not cfg.video_api_url or not cfg.video_api_key:
        raise ValueError(
            "DashScope backend requires VIDEO_API_URL and VIDEO_API_KEY"
        )

    url = cfg.video_api_url.rstrip("/")  # strip trailing slash to avoid double //

    headers = {
        "Authorization": f"Bearer {cfg.video_api_key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }

    payload = _build_dashscope_video_payload(
        model, prompt, images, duration, resolution, ratio,
    )

    logger.info(
        "Submitting DashScope video job | model={} prompt={!r} n_images={} params={}",
        model, prompt, len(images), payload["parameters"],
    )
    resp = requests.post(url, json=payload, headers=headers)
    if not resp.ok:
        logger.error("DashScope video API error | status={} body={}", resp.status_code, resp.text)
        _raise_dashscope_error(resp)

    data = resp.json()
    task_id = data["output"]["task_id"]
    logger.info("DashScope video job submitted | task_id={}", task_id)
    return {"task_id": task_id}


def _build_dashscope_video_payload(
    model: str,
    prompt: str,
    images: list[bytes],
    duration: int | str | None = None,
    resolution: str | None = None,
    ratio: str | None = None,
) -> dict:
    """Build the video generation payload for a DashScope model.

    Models in the capability table get their media type and parameter ranges
    from that table; anything else falls back to the historic payload.
    """
    spec = video_spec(model)
    if spec is None:
        return _build_legacy_dashscope_payload(model, prompt, images)

    _check_video_images(model, spec, len(images))

    parameters: dict = {
        "resolution": _pick_value(resolution, spec.resolutions, spec.default_resolution, model),
        "duration": _pick_duration(duration, spec, model),
        "watermark": False,
    }
    if spec.ratios:
        parameters["ratio"] = _pick_value(ratio, spec.ratios, spec.default_ratio, model)

    payload: dict = {
        "model": model,
        "input": {"prompt": prompt},
        "parameters": parameters,
    }

    if images:
        if spec.media == "first_frame":
            payload["input"]["media"] = [
                {"type": "first_frame", "url": _mime_and_b64(images[0])},
            ]
        else:
            # ponytail: ~117MB for 10 x 5MB images
            payload["input"]["media"] = [
                {"type": "reference_image", "url": _mime_and_b64(img)} for img in images
            ]

    return payload


def _build_legacy_dashscope_payload(
    model: str,
    prompt: str,
    images: list[bytes],
) -> dict:
    """Payload for models outside the capability table (e.g. wan2.6).

    wan2.6 takes the first image as img_url, every newer model takes a
    media[] list.
    """
    use_media = "wan2.6" not in model
    payload: dict = {
        "model": model,
        "input": {"prompt": prompt},
        "parameters": {
            "resolution": "720P",
            "duration": 5,
            "watermark": False,
        },
    }

    if images:
        if use_media:
            payload["input"]["media"] = [
                {"type": "reference_image", "url": _mime_and_b64(img)} for img in images
            ]
        else:
            payload["input"]["img_url"] = _mime_and_b64(images[0])

    return payload


def _check_video_images(model: str, spec: VideoSpec, count: int) -> None:
    """Reject an image count the model cannot take."""
    if spec.media is None:
        if count:
            raise ValueError(
                f"{model} is a text-to-video model and does not accept reference images"
            )
        return
    if count < spec.min_images:
        raise ValueError(
            f"{model} needs at least {spec.min_images} reference image(s), got {count}"
        )
    if count > spec.max_images:
        raise ValueError(
            f"{model} accepts at most {spec.max_images} reference image(s), got {count}"
        )


def _pick_value(
    requested: str | None,
    allowed: tuple[str, ...],
    default: str | None,
    model: str,
) -> str | None:
    """Use the requested value when the model accepts it, else the default."""
    if requested in allowed:
        return requested
    if requested is not None:
        logger.warning(
            "Unsupported value for model | model={} requested={!r} using={}",
            model, requested, default,
        )
    return default


def _pick_duration(
    requested: int | str | None,
    spec: VideoSpec,
    model: str,
) -> int:
    """Clamp the requested duration into the range the model accepts."""
    if requested is None:
        return spec.default_duration
    try:
        value = int(requested)
    except (TypeError, ValueError):
        logger.warning(
            "Unusable duration for model | model={} requested={!r} using={}",
            model, requested, spec.default_duration,
        )
        return spec.default_duration
    clamped = max(spec.duration_min, min(spec.duration_max, value))
    if clamped != value:
        logger.warning(
            "Duration out of range for model | model={} requested={} using={}",
            model, value, clamped,
        )
    return clamped


def _raise_dashscope_error(resp):
    """Parse DashScope error response and raise with the message field."""
    try:
        body = resp.json()
        message = body.get("message", resp.text)
    except Exception:
        message = resp.text
    raise RuntimeError(f"DashScope error {resp.status_code}: {message}")


def _poll_dashscope(cfg: Config, submit: dict) -> dict:
    task_id = submit["task_id"]
    # Poll URL is at a different path than submit: {hostname}/api/v1/tasks/{task_id}
    parsed = urlparse(cfg.video_api_url)
    url = f"{parsed.scheme}://{parsed.netloc}/api/v1/tasks/{task_id}"
    headers = {"Authorization": f"Bearer {cfg.video_api_key}"}

    resp = requests.get(url, headers=headers)
    if not resp.ok:
        logger.error("DashScope video poll error | status={} body={}", resp.status_code, resp.text)
        _raise_dashscope_error(resp)

    data = resp.json()
    status = data.get("output", {}).get("task_status", "UNKNOWN")
    logger.debug("DashScope video poll | task_id={} status={}", task_id, status)

    if status == "SUCCEEDED":
        video_url = data["output"].get("video_url")
        if not video_url:
            return {"status": "error", "message": "SUCCEEDED but no video_url in response"}
        logger.info("DashScope video job complete | task_id={} url={}", task_id, video_url)
        video_resp = requests.get(video_url)
        video_resp.raise_for_status()
        return {"status": "done", "video_data": video_resp.content}
    elif status in ("PENDING", "RUNNING"):
        return {"status": "pending", "queue_position": None}
    elif status == "FAILED":
        message = data.get("output", {}).get("message", "DashScope video generation failed")
        logger.error("DashScope video job failed | task_id={}", task_id)
        return {"status": "error", "message": message}
    else:
        # CANCELED, UNKNOWN, or any other status
        return {"status": "error", "message": f"DashScope video task status: {status}"}


# ------------------------------------------------------------------ #
# Dummy backend -- no network, no cost                                 #
# ------------------------------------------------------------------ #

_DUMMY_POLLS_UNTIL_DONE = 3


def _start_dummy() -> dict:
    """Submit a dummy video job.  The counter lives in the returned dict --
    poll_video_job reuses it on every call (app.py:264), so no module-level
    state, no cross-job interference."""
    return {"dummy": True, "polls": 0}


def _poll_dummy(submit: dict) -> dict:
    submit["polls"] += 1
    if submit["polls"] >= _DUMMY_POLLS_UNTIL_DONE:
        return {"status": "done", "video_data": _dummy_video_bytes()}
    return {"status": "pending",
            "queue_position": (_DUMMY_POLLS_UNTIL_DONE - submit["polls"])}


def _dummy_video_bytes() -> bytes:
    """Read the committed MP4 asset.  Path is relative to this module's file,
    never to the working directory -- the app chdirs at startup under the
    data-dir design."""
    return (Path(__file__).parent / "assets" / "dummy.mp4").read_bytes()
