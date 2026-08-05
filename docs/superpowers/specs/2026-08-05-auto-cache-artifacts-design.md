# Auto-cache generated artifacts to `.cache/`

## Goal

Every generated image/video is automatically saved to `.cache/` when the job completes, regardless of whether the user downloads it.

## Filename format

```
.cache/YYYYMMDD/YYYYMMDD-HHMMSS-{job_id}.{ext}
```

Example: `.cache/20260805/20260805-151800-0a545699-e793-47d7-a911-8c849bfc447a.png`

- Date subdirectory groups files by day
- `job_id` is the UUID assigned by `job_store.create_job()`
- Extension: `.png` for images, `.mp4` for videos (assumes all backends return PNG/MP4 — true for current backends)

## What gets cached

| Job type | Backend | Cached as | Content |
|----------|---------|-----------|---------|
| Image | openai, azure, fal, dashscope | `.png` | Raw image bytes |
| Image (SD) | InvokeAI | `.png` | Raw image bytes |
| Video | azure, dashscope, fal | `.mp4` | Raw video bytes |

All backends cache actual bytes. For fal videos (which return only a URL), we fetch the bytes at job completion time — same fetch that `serve_video` already does on demand.

## Infrastructure

- `.cache/` added to `.gitignore`
- `from datetime import datetime` added to `app.py`

## Implementation

### Helper function in `app.py`

```python
def _cache_artifact(job_id: str, data: bytes, ext: str):
    now = datetime.now()
    today = now.strftime("%Y%m%d")
    ts = now.strftime("%Y%m%d-%H%M%S")
    cache_dir = os.path.join(".cache", today)
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"{ts}-{job_id}.{ext}")
    with open(path, "wb") as f:
        f.write(data)
    logger.info("Cached artifact | path={} size={} bytes", path, len(data))
```

Note: `datetime.now()` called once to avoid midnight race condition.

### Call-site placement

Cache write goes **before** `job_store.update_job(status: "done")`, wrapped in its own try/except. This ensures:
1. A cache failure never marks the job as "error" (the outer except won't catch it)
2. If the process crashes after `update_job` but before cache, the artifact still made it to disk

### Call sites (background workers in `app.py`)

1. `_run_image_job` — after `generate_image()`, before `update_job`:
   ```python
   try:
       _cache_artifact(job_id, data, "png")
   except Exception:
       logger.warning("Failed to cache artifact | job_id={}", job_id, exc_info=True)
   job_store.update_job(job_id, {"status": "done", "output_type": "image", "data": data})
   ```

2. `_run_sd_job` — same pattern: cache then update

3. `_run_video_job` — in the success branch:
   ```python
   if "video_data" in result:
       update["video_data"] = result["video_data"]
       try:
           _cache_artifact(job_id, result["video_data"], "mp4")
       except Exception:
           logger.warning("Failed to cache artifact | job_id={}", job_id, exc_info=True)
   else:
       # fal: fetch bytes for caching
       video_data = requests.get(result["video_url"]).content
       update["video_data"] = video_data
       try:
           _cache_artifact(job_id, video_data, "mp4")
       except Exception:
           logger.warning("Failed to cache artifact | job_id={}", job_id, exc_info=True)
   job_store.update_job(job_id, update)
   ```

   Note: fal branch now stores `video_data` in the job too, making subsequent `serve_video` calls faster (no re-fetch).

### Error handling

Cache write failure logs a warning but **never fails the job**. The in-memory artifact is the source of truth; cache is a convenience copy.

### What is NOT in scope

- Cache cleanup / max size / TTL — add when disk pressure is real
- Cache index or listing endpoint — add when browsing is needed
- Deduplication — each job has a unique UUID, no collision possible

## Testing

One test: call `_cache_artifact` with known inputs, verify file exists at the expected path with correct content.
