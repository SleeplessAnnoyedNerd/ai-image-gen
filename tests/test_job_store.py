from services import job_store


def setup_function():
    job_store._jobs.clear()


def test_create_job_returns_unique_ids():
    id1 = job_store.create_job()
    id2 = job_store.create_job()
    assert id1 != id2


def test_new_job_has_pending_status():
    job_id = job_store.create_job()
    job = job_store.get_job(job_id)
    assert job["status"] == "pending"


def test_update_job():
    job_id = job_store.create_job()
    job_store.update_job(job_id, {"status": "done", "output_type": "image", "data": b"bytes"})
    job = job_store.get_job(job_id)
    assert job["status"] == "done"
    assert job["data"] == b"bytes"


def test_get_missing_job_returns_none():
    assert job_store.get_job("nonexistent") is None
