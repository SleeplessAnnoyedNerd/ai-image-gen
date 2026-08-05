import io
import os
import threading
from datetime import datetime
from loguru import logger
import requests as _requests

_port = os.environ.get("PORT", "5000")
logger.add(
    f"logs/app-{_port}.log",
    rotation="10 MB", retention=5, level="DEBUG",
    backtrace=True, diagnose=True,
    format="{time:YYYY-MM-DD HH:mm:ss.SSS Z} | {level:<8} | {name}:{function}:{line} - {message}",
)

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, send_file, abort, jsonify
)
from config import Config
from translations import get_strings
from services import job_store, image_gen, video_gen, sd_gen


def _cache_artifact(job_id: str, data: bytes, ext: str):
    """Write artifact bytes to .cache/YYYYMMDD/YYYYMMDD-HHMMSS-{job_id}.{ext}."""
    now = datetime.now()
    today = now.strftime("%Y%m%d")
    ts = now.strftime("%Y%m%d-%H%M%S")
    cache_dir = os.path.join(".cache", today)
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"{ts}-{job_id}.{ext}")
    with open(path, "wb") as f:
        f.write(data)
    logger.info("Cached artifact | path={} size={} bytes", path, len(data))


def create_app(cfg: Config | None = None) -> Flask:
    app = Flask(__name__)

    if cfg is None:
        cfg = Config.from_env()
    app.secret_key = cfg.secret_key

    def t():
        return get_strings(session.get("lang", "en"))

    # ------------------------------------------------------------------ #
    # Pages                                                                #
    # ------------------------------------------------------------------ #

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            t=t(),
            sd_enabled=bool(cfg.sd_api_url),
            image_models=cfg.image_model,
            image_models_edit=cfg.image_model_edit,
            video_models_image=cfg.video_model_image,
            video_models_text=cfg.video_model_text,
        )

    @app.post("/lang")
    def set_lang():
        lang = request.form.get("lang", "en")
        session["lang"] = lang if lang in ("en", "de") else "en"
        return redirect(url_for("index"))

    @app.get("/sd-status")
    def sd_status():
        if not cfg.sd_api_url:
            return jsonify({"online": False})
        try:
            r = _requests.get(f"{cfg.sd_api_url}/api/v1/app/version", timeout=3)
            return jsonify({"online": r.ok})
        except Exception:
            return jsonify({"online": False})

    # ------------------------------------------------------------------ #
    # Generation                                                           #
    # ------------------------------------------------------------------ #

    @app.post("/generate")
    def generate():
        output_type = request.form.get("output_type", "image")
        prompt = request.form.get("prompt", "").strip()
        image_file = request.files.get("image")
        image_bytes = (
            image_file.read()
            if image_file and image_file.filename
            else None
        )

        image_model       = request.form.get("image_model")       or cfg.image_model[0]
        image_model_edit  = request.form.get("image_model_edit")  or cfg.image_model_edit[0]
        video_model_image = request.form.get("video_model_image") or cfg.video_model_image[0]
        video_model_text  = request.form.get("video_model_text")  or cfg.video_model_text[0]

        job_id = job_store.create_job()
        logger.info("Job created | job_id={} output_type={} prompt={!r}", job_id, output_type, prompt)

        if output_type == "image":
            threading.Thread(
                target=_run_image_job,
                args=(cfg, job_id, prompt, image_bytes, image_model, image_model_edit),
                daemon=True,
            ).start()
        elif output_type == "sd":
            threading.Thread(
                target=_run_sd_job,
                args=(cfg, job_id, prompt, image_bytes),
                daemon=True,
            ).start()
        else:
            threading.Thread(
                target=_run_video_job,
                args=(cfg, job_id, prompt, image_bytes, video_model_image, video_model_text),
                daemon=True,
            ).start()

        return render_template(
            "partials/generating.html", job_id=job_id, t=t()
        )

    @app.get("/status/<job_id>")
    def status(job_id):
        job = job_store.get_job(job_id)
        strings = t()
        if not job:
            return render_template("partials/error.html",
                                   message=strings["error_generic"], t=strings)
        if job["status"] == "pending":
            return render_template("partials/generating.html",
                                   job_id=job_id, t=strings,
                                   progress=job.get("progress"))
        if job["status"] == "done":
            if job["output_type"] == "image":
                return render_template("partials/result_image.html",
                                       job_id=job_id, t=strings)
            else:
                return render_template("partials/result_video.html",
                                       job_id=job_id,
                                       t=strings)
        return render_template("partials/error.html",
                               message=job.get("error", strings["error_generic"]),
                               t=strings)

    @app.get("/image/<job_id>")
    def serve_image(job_id):
        job = job_store.get_job(job_id)
        if not job:
            logger.warning("serve_image: job not found | job_id={}", job_id)
            abort(404)
        if job.get("status") != "done" or job.get("output_type") != "image":
            logger.warning("serve_image: job not ready | job_id={} status={} output_type={}", job_id, job.get("status"), job.get("output_type"))
            abort(404)
        data = job["data"]
        logger.info("serve_image: serving | job_id={} size={} bytes", job_id, len(data) if data else 0)
        return send_file(
            io.BytesIO(data),
            mimetype="image/png",
        )

    @app.get("/video/<job_id>")
    def serve_video(job_id):
        job = job_store.get_job(job_id)
        if not job or job.get("status") != "done" or job.get("output_type") != "video":
            abort(404)
        data = job["video_data"]
        return send_file(io.BytesIO(data), mimetype="video/mp4")

    @app.get("/download/<job_id>")
    def download(job_id):
        job = job_store.get_job(job_id)
        if not job or job.get("status") != "done":
            abort(404)
        if job["output_type"] == "image":
            return send_file(
                io.BytesIO(job["data"]),
                mimetype="image/png",
                as_attachment=True,
                download_name=f"{job_id}.png",
            )
        else:
            return send_file(
                io.BytesIO(job["video_data"]),
                mimetype="video/mp4",
                as_attachment=True,
                download_name=f"{job_id}.mp4",
            )

    return app


# ------------------------------------------------------------------ #
# Background workers                                                   #
# ------------------------------------------------------------------ #

def _run_image_job(cfg: Config, job_id: str, prompt: str, image_bytes: bytes | None,
                   model: str, model_edit: str):
    try:
        data = image_gen.generate_image(cfg, prompt, image_bytes, model=model, model_edit=model_edit)
        job_store.update_job(job_id, {"status": "done", "output_type": "image", "data": data})
        logger.info("Image job done | job_id={}", job_id)
    except Exception as exc:
        logger.exception("Image job failed | job_id={}", job_id)
        job_store.update_job(job_id, {"status": "error", "error": str(exc)})


def _run_sd_job(cfg: Config, job_id: str, prompt: str, image_bytes: bytes | None):
    try:
        data = sd_gen.generate_image_sd(cfg, prompt, image_bytes)
        job_store.update_job(job_id, {"status": "done", "output_type": "image", "data": data})
        logger.info("SD job done | job_id={}", job_id)
    except Exception as exc:
        logger.exception("SD job failed | job_id={}", job_id)
        job_store.update_job(job_id, {"status": "error", "error": str(exc)})


def _run_video_job(cfg: Config, job_id: str, prompt: str, image_bytes: bytes | None,
                   model_image: str, model_text: str):
    import time
    try:
        submit = video_gen.start_video_job(
            cfg, prompt, image_bytes,
            model_image=model_image, model_text=model_text,
        )
        for _ in range(300):
            time.sleep(2)
            result = video_gen.poll_video_job(cfg, submit)
            qp = result.get("queue_position")
            job_store.update_job(job_id, {
                "progress": "in_progress" if qp is None else str(qp)
            })
            if result["status"] == "done":
                update = {"status": "done", "output_type": "video"}
                if "video_data" in result:
                    update["video_data"] = result["video_data"]
                else:
                    update["video_url"] = result["video_url"]
                job_store.update_job(job_id, update)
                return
            if result["status"] == "error":
                raise RuntimeError(result.get("message", "Video generation failed"))
        raise TimeoutError("Video generation timed out after 10 minutes")
    except Exception as exc:
        logger.exception("Video job failed | job_id={}", job_id)
        job_store.update_job(job_id, {"status": "error", "error": str(exc)})


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()
    port = args.port if args.port is not None else int(os.environ.get("PORT", 5000))
    if str(port) != _port:
        # CLI port differs from env — re-add log handler with correct port name
        logger.add(
            f"logs/app-{port}.log",
            rotation="10 MB", retention=5, level="DEBUG",
            backtrace=True, diagnose=True,
            format="{time:YYYY-MM-DD HH:mm:ss.SSS Z} | {level:<8} | {name}:{function}:{line} - {message}",
        )
    app = create_app()
    app.run(host="0.0.0.0", port=port, debug=False)
