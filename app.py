import io
import os
import subprocess
import threading
from datetime import datetime
from loguru import logger
import requests as _requests

from config import _get, resolve_data_dir

# Everything this app writes — logs/, .cache/, prompts.db — is a path relative
# to the working directory, so anchoring the working directory once, here, is
# all it takes to make them configurable together.
#
# This must run before the logger.add() below: loguru opens its file sink
# immediately and keeps that handle for the life of the process, so a later
# chdir would leave the log behind in the old directory.
_DATA_DIR = resolve_data_dir()
_DATA_DIR.mkdir(parents=True, exist_ok=True)
os.chdir(_DATA_DIR)

_port = str(_get("flask", "port", "5000"))
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
from services import job_store, image_gen, video_gen, sd_gen, prompt_store

_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB per file
_MAX_IMAGES = 10


def _git_hash() -> str:
    """Short git commit hash, or empty string if unavailable."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return ""


_GIT_HASH = _git_hash()


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
    app.config["MAX_CONTENT_LENGTH"] = 120 * 1024 * 1024  # 120MB total request cap

    if cfg is None:
        cfg = Config.from_settings()
    app.secret_key = cfg.secret_key

    def t():
        return get_strings(session.get("lang", "en"))

    @app.context_processor
    def _inject_git_hash():
        return {"git_hash": _GIT_HASH}

    # ------------------------------------------------------------------ #
    # Pages                                                                #
    # ------------------------------------------------------------------ #

    def _picker_context(query: str = ""):
        """Context for partials/prompt_results.html.

        Pinned rows also satisfy recent()'s WHERE clause, so they are filtered
        out here -- the store has no cross-query knowledge. This can leave 22
        rows instead of 25; that is fine, do not over-fetch to compensate.
        """
        if (query):
            rows, regex_error, total = prompt_store.search(query)
            return {"pinned": [], "prompts": rows, "query": query,
                    "regex_error": regex_error, "total": total}
        pinned = prompt_store.top(3, cfg.prompt_min_use_count)
        seen = {row.text for row in pinned}
        prompts = [row for row in prompt_store.recent(25, cfg.prompt_min_use_count)
                   if (row.text not in seen)]
        return {"pinned": pinned, "prompts": prompts, "query": "",
                "regex_error": False, "total": len(prompts)}

    @app.get("/")
    def index():
        image_backends = {
            name: {"model": bc.model, "model_edit": bc.model_edit}
            for name, bc in cfg.image_backends.items()
        }
        return render_template(
            "index.html",
            t=t(),
            sd_enabled=bool(cfg.sd_api_url),
            image_backends=image_backends,
            image_default_backend=cfg.image_default_backend,
            video_models_image=cfg.video_model_image,
            video_models_text=cfg.video_model_text,
            **_picker_context(),
        )

    @app.get("/prompts")
    def prompts():
        # Strip here, not only inside search(): htmx sends ?q=%20 for a lone
        # space, which is truthy but means "no query".
        query = request.args.get("q", "").strip()
        return render_template("partials/prompt_results.html", t=t(),
                               **_picker_context(query))

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
        prompt_store.add(prompt)

        # Read all uploaded files, filter empty filenames and empty/oversized files
        raw_files = request.files.getlist("images")
        images = []
        for f in raw_files:
            if not f.filename:
                continue
            data = f.read()
            if len(data) == 0:
                continue
            if len(data) > _MAX_FILE_SIZE:
                logger.warning("Skipping oversized file | name={} size={} bytes", f.filename, len(data))
                continue
            images.append(data)

        if len(images) > _MAX_IMAGES:
            abort(400)

        image_backend = request.form.get("image_backend") or cfg.image_default_backend
        if image_backend not in cfg.image_backends:
            abort(400)
        bc = cfg.image_backends[image_backend]

        image_model       = request.form.get("image_model")       or bc.model[0]
        image_model_edit  = request.form.get("image_model_edit")  or bc.model_edit[0]
        video_model_image = request.form.get("video_model_image") or cfg.video_model_image[0]
        video_model_text  = request.form.get("video_model_text")  or cfg.video_model_text[0]

        job_id = job_store.create_job()
        logger.info("Job created | job_id={} output_type={} prompt={!r} n_images={}", job_id, output_type, prompt, len(images))

        if output_type == "image":
            threading.Thread(
                target=_run_image_job,
                args=(cfg, job_id, prompt, images, image_backend, image_model, image_model_edit),
                daemon=True,
            ).start()
        elif output_type == "sd":
            threading.Thread(
                target=_run_sd_job,
                args=(cfg, job_id, prompt, images),
                daemon=True,
            ).start()
        else:
            threading.Thread(
                target=_run_video_job,
                args=(cfg, job_id, prompt, images, video_model_image, video_model_text),
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

def _run_image_job(cfg: Config, job_id: str, prompt: str, images: list[bytes],
                   backend: str, model: str, model_edit: str):
    try:
        data = image_gen.generate_image(cfg, prompt, images, backend=backend, model=model, model_edit=model_edit)
        try:
            _cache_artifact(job_id, data, "png")
        except Exception:
            logger.warning("Failed to cache artifact | job_id={}", job_id, exc_info=True)
        job_store.update_job(job_id, {"status": "done", "output_type": "image", "data": data})
        logger.info("Image job done | job_id={}", job_id)
    except Exception as exc:
        logger.exception("Image job failed | job_id={}", job_id)
        job_store.update_job(job_id, {"status": "error", "error": str(exc)})


def _run_sd_job(cfg: Config, job_id: str, prompt: str, images: list[bytes]):
    try:
        data = sd_gen.generate_image_sd(cfg, prompt, images)
        try:
            _cache_artifact(job_id, data, "png")
        except Exception:
            logger.warning("Failed to cache artifact | job_id={}", job_id, exc_info=True)
        job_store.update_job(job_id, {"status": "done", "output_type": "image", "data": data})
        logger.info("SD job done | job_id={}", job_id)
    except Exception as exc:
        logger.exception("SD job failed | job_id={}", job_id)
        job_store.update_job(job_id, {"status": "error", "error": str(exc)})


def _run_video_job(cfg: Config, job_id: str, prompt: str, images: list[bytes],
                   model_image: str, model_text: str):
    import time
    try:
        submit = video_gen.start_video_job(
            cfg, prompt, images,
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
                try:
                    _cache_artifact(job_id, result["video_data"], "mp4")
                except Exception:
                    logger.warning("Failed to cache artifact | job_id={}", job_id, exc_info=True)
                job_store.update_job(job_id, {
                    "status": "done", "output_type": "video",
                    "video_data": result["video_data"],
                })
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
    port = args.port if args.port is not None else int(_get("flask", "port", "5000"))
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
