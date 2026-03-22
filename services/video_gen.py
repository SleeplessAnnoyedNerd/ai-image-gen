import base64
import requests
from loguru import logger
from config import Config


def start_video_job(
    cfg: Config, prompt: str, image_bytes: bytes | None
) -> dict:
    """Submit a video generation job.
    Returns the full submit response dict (contains request_id, status_url, response_url).
    """
    if image_bytes is not None:
        model = cfg.video_model_image
        img_b64 = base64.b64encode(image_bytes).decode()
        payload = {
            "prompt": prompt,
            "image_url": f"data:image/jpeg;base64,{img_b64}",
        }
    else:
        model = cfg.video_model_text
        payload = {"prompt": prompt}

    url = f"{cfg.video_api_url}/{model}"
    headers = {
        "Authorization": f"Key {cfg.video_api_key}",
        "Content-Type": "application/json",
    }
    logger.info("Submitting video job | model={} prompt={!r} has_image={}", model, prompt, image_bytes is not None)
    resp = requests.post(url, json=payload, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    logger.info("Video job submitted | request_id={} status_url={}", data.get("request_id"), data.get("status_url"))
    return data


def poll_video_job(cfg: Config, status_url: str, response_url: str) -> dict:
    """Poll fal.ai queue using the URLs returned at submit time. Returns status dict."""
    headers = {"Authorization": f"Key {cfg.video_api_key}"}

    resp = requests.get(status_url, headers=headers)
    resp.raise_for_status()
    status = resp.json().get("status")

    if status == "COMPLETED":
        result = requests.get(response_url, headers=headers)
        result.raise_for_status()
        video_url = result.json()["video"]["url"]
        logger.info("Video job complete | url={}", video_url)
        return {"status": "done", "video_url": video_url}
    elif status == "FAILED":
        logger.error("Video job failed | status_url={}", status_url)
        return {"status": "error", "message": "Video generation failed"}
    elif status == "IN_PROGRESS":
        logger.debug("Video job in progress")
        return {"status": "pending", "queue_position": None}
    else:
        queue_position = resp.json().get("queue_position")
        logger.debug("Video job queued | queue_position={}", queue_position)
        return {"status": "pending", "queue_position": queue_position}
