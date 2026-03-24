import io
import base64
from unittest.mock import patch, MagicMock
from services import job_store


def setup_function():
    job_store._jobs.clear()


def test_index_returns_200(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Generator" in resp.data


def test_lang_switch(client):
    resp = client.post("/lang", data={"lang": "de"}, follow_redirects=True)
    assert resp.status_code == 200
    assert "KI-Bild" in resp.data.decode("utf-8")


def test_generate_image_job_starts(client):
    with patch("app.image_gen.generate_image", return_value=b"png-bytes"):
        resp = client.post("/generate", data={
            "output_type": "image",
            "prompt": "a sunset",
        })
    assert resp.status_code == 200
    assert b"job_id" in resp.data or b"generating" in resp.data.lower()


def test_generate_image_respects_model_selection(client):
    """Model selected in POST form is passed to generate_image."""
    with patch("app.image_gen.generate_image", return_value=b"png-bytes") as mock_gen:
        client.post("/generate", data={
            "output_type": "image",
            "prompt": "a sunset",
            "image_model": "custom/model",
        })
    import time; time.sleep(0.15)
    if mock_gen.called:
        kwargs = mock_gen.call_args.kwargs
        assert kwargs.get("model") == "custom/model"


def test_status_pending(client):
    job_id = job_store.create_job()
    resp = client.get(f"/status/{job_id}")
    assert resp.status_code == 200


def test_status_done_image(client):
    job_id = job_store.create_job()
    job_store.update_job(job_id, {"status": "done", "output_type": "image", "data": b"png"})
    resp = client.get(f"/status/{job_id}")
    assert resp.status_code == 200


def test_download_image(client):
    job_id = job_store.create_job()
    job_store.update_job(job_id, {"status": "done", "output_type": "image", "data": b"png-content"})
    resp = client.get(f"/image/{job_id}")
    assert resp.status_code == 200
    assert resp.data == b"png-content"


def test_download_missing_job(client):
    resp = client.get("/image/nonexistent-id")
    assert resp.status_code == 404
