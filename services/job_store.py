import threading
import uuid

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def create_job() -> str:
    job_id = str(uuid.uuid4())
    with _lock:
        _jobs[job_id] = {"status": "pending"}
    return job_id


def update_job(job_id: str, data: dict) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(data)


def get_job(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job is not None else None
