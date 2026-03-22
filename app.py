import io
import threading
from loguru import logger
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, send_file, abort
)
from config import Config
from translations import get_strings
from services import job_store, image_gen, video_gen


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
        return render_template("index.html", t=t())

    @app.post("/lang")
    def set_lang():
        lang = request.form.get("lang", "en")
        session["lang"] = lang if lang in ("en", "de") else "en"
        return redirect(url_for("index"))

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

        job_id = job_store.create_job()
        logger.info("Job created | job_id={} output_type={} prompt={!r}", job_id, output_type, prompt)

        if output_type == "image":
            threading.Thread(
                target=_run_image_job,
                args=(cfg, job_id, prompt, image_bytes),
                daemon=True,
            ).start()
        else:
            threading.Thread(
                target=_run_video_job,
                args=(cfg, job_id, prompt, image_bytes),
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
                                   job_id=job_id, t=strings)
        if job["status"] == "done":
            if job["output_type"] == "image":
                return render_template("partials/result_image.html",
                                       job_id=job_id, t=strings)
            else:
                return render_template("partials/result_video.html",
                                       job_id=job_id,
                                       video_url=job.get("video_url"),
                                       t=strings)
        return render_template("partials/error.html",
                               message=job.get("error", strings["error_generic"]),
                               t=strings)

    @app.get("/image/<job_id>")
    def serve_image(job_id):
        job = job_store.get_job(job_id)
        if not job or job.get("status") != "done" or job.get("output_type") != "image":
            abort(404)
        return send_file(
            io.BytesIO(job["data"]),
            mimetype="image/png",
        )

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
                download_name="generated.png",
            )
        else:
            return redirect(job["video_url"])

    return app


# ------------------------------------------------------------------ #
# Background workers                                                   #
# ------------------------------------------------------------------ #

def _run_image_job(cfg: Config, job_id: str, prompt: str, image_bytes: bytes | None):
    try:
        data = image_gen.generate_image(cfg, prompt, image_bytes)
        job_store.update_job(job_id, {"status": "done", "output_type": "image", "data": data})
        logger.info("Image job done | job_id={}", job_id)
    except Exception as exc:
        logger.exception("Image job failed | job_id={}", job_id)
        job_store.update_job(job_id, {"status": "error", "error": str(exc)})


def _run_video_job(cfg: Config, job_id: str, prompt: str, image_bytes: bytes | None):
    import time
    try:
        request_id, model = video_gen.start_video_job(cfg, prompt, image_bytes)
        for _ in range(120):          # poll up to 4 minutes (120 × 2s)
            time.sleep(2)
            result = video_gen.poll_video_job(cfg, request_id, model)
            if result["status"] == "done":
                job_store.update_job(job_id, {
                    "status": "done",
                    "output_type": "video",
                    "video_url": result["video_url"],
                })
                return
            if result["status"] == "error":
                raise RuntimeError(result.get("message", "Video generation failed"))
        raise TimeoutError("Video generation timed out after 4 minutes")
    except Exception as exc:
        logger.exception("Video job failed | job_id={}", job_id)
        job_store.update_job(job_id, {"status": "error", "error": str(exc)})


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=False)
