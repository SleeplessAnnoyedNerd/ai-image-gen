import base64
import requests
from config import Config


def start_video_job(
    cfg: Config, prompt: str, image_bytes: bytes | None
) -> tuple[str, str]:
    """Submit a video generation job. Returns (request_id, model)."""
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
    resp = requests.post(url, json=payload, headers=headers)
    resp.raise_for_status()
    request_id = resp.json()["request_id"]
    return request_id, model


def poll_video_job(cfg: Config, request_id: str, model: str) -> dict:
    """Poll fal.ai queue for job status. Returns status dict."""
    headers = {"Authorization": f"Key {cfg.video_api_key}"}
    status_url = f"{cfg.video_api_url}/{model}/requests/{request_id}/status"

    resp = requests.get(status_url, headers=headers)
    resp.raise_for_status()
    status = resp.json().get("status")

    if status == "COMPLETED":
        result_url = f"{cfg.video_api_url}/{model}/requests/{request_id}"
        result = requests.get(result_url, headers=headers)
        result.raise_for_status()
        video_url = result.json()["video"]["url"]
        return {"status": "done", "video_url": video_url}
    elif status == "FAILED":
        return {"status": "error", "message": "Video generation failed"}
    else:
        return {"status": "pending"}
