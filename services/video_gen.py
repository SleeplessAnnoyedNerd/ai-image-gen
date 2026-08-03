import base64
import requests
from urllib.parse import urlparse
from loguru import logger
from config import Config


def start_video_job(
    cfg: Config,
    prompt: str,
    image_bytes: bytes | None,
    model_image: str | None = None,
    model_text: str | None = None,
) -> dict:
    """Submit a video generation job. Returns a submit-context dict for poll_video_job."""
    model_image = model_image or cfg.video_model_image[0]
    model_text = model_text or cfg.video_model_text[0]
    if cfg.video_backend == "azure":
        return _start_azure(cfg, prompt, image_bytes, model_image, model_text)
    if cfg.video_backend == "dashscope":
        return _start_dashscope(cfg, prompt, image_bytes, model_image, model_text)
    return _start_fal(cfg, prompt, image_bytes, model_image, model_text)


def poll_video_job(cfg: Config, submit: dict) -> dict:
    """Poll a previously submitted job.
    Keys: status ("pending"|"done"|"error"), queue_position (int|None),
          video_url (str, fal) OR video_data (bytes, azure), message (str on error).
    """
    if cfg.video_backend == "azure":
        return _poll_azure(cfg, submit)
    if cfg.video_backend == "dashscope":
        return _poll_dashscope(cfg, submit)
    return _poll_fal(cfg, submit)


# ------------------------------------------------------------------ #
# fal.ai backend                                                       #
# ------------------------------------------------------------------ #

def _start_fal(
    cfg: Config,
    prompt: str,
    image_bytes: bytes | None,
    model_image: str,
    model_text: str,
) -> dict:
    if image_bytes is not None:
        model = model_image
        img_b64 = base64.b64encode(image_bytes).decode()
        payload = {
            "prompt": prompt,
            "image_url": f"data:image/jpeg;base64,{img_b64}",
        }
    else:
        model = model_text
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
        return {"status": "done", "video_url": video_url}
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
    model_image: str,
    model_text: str,
) -> dict:
    deployment = model_image if image_bytes else model_text
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
    if image_bytes is not None:
        mime = "image/png" if image_bytes[:4] == b'\x89PNG' else "image/jpeg"
        payload["first_frame_image"] = (
            f"data:{mime};base64,{base64.b64encode(image_bytes).decode()}"
        )

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
    image_bytes: bytes | None,
    model_image: str,
    model_text: str,
) -> dict:
    if not cfg.video_api_url or not cfg.video_api_key:
        raise ValueError(
            "DashScope backend requires VIDEO_API_URL and VIDEO_API_KEY"
        )

    active_model = model_image if image_bytes is not None else model_text
    url = cfg.video_api_url.rstrip("/")  # strip trailing slash to avoid double //

    payload: dict = {
        "model": active_model,
        "input": {"prompt": prompt},
        "parameters": {
            "resolution": "720P",
            "duration": 5,
            "watermark": False,
        },
    }

    if image_bytes is not None:
        mime = "image/png" if image_bytes[:4] == b'\x89PNG' else "image/jpeg"
        b64 = base64.b64encode(image_bytes).decode()
        payload["input"]["media"] = [
            {"type": "reference_image", "url": f"data:{mime};base64,{b64}"}
        ]

    headers = {
        "Authorization": f"Bearer {cfg.video_api_key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }

    logger.info(
        "Submitting DashScope video job | model={} prompt={!r} has_image={}",
        active_model, prompt, image_bytes is not None,
    )
    resp = requests.post(url, json=payload, headers=headers)
    resp.raise_for_status()

    data = resp.json()
    task_id = data["output"]["task_id"]
    logger.info("DashScope video job submitted | task_id={}", task_id)
    return {"task_id": task_id}


def _poll_dashscope(cfg: Config, submit: dict) -> dict:
    task_id = submit["task_id"]
    # Poll URL is at a different path than submit: {hostname}/api/v1/tasks/{task_id}
    parsed = urlparse(cfg.video_api_url)
    url = f"{parsed.scheme}://{parsed.netloc}/api/v1/tasks/{task_id}"
    headers = {"Authorization": f"Bearer {cfg.video_api_key}"}

    resp = requests.get(url, headers=headers)
    resp.raise_for_status()

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
