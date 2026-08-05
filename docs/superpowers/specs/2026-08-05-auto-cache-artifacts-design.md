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
- Extension: `.png` for images, `.mp4` for videos, `.txt` for URL-only video results (fal backend)

## What gets cached

| Job type | Backend | Cached as | Content |
|----------|---------|-----------|---------|
| Image | openai, azure, fal, dashscope | `.png` | Raw image bytes |
| Image (SD) | InvokeAI | `.png` | Raw image bytes |
| Video | azure, dashscope | `.mp4` | Raw video bytes |
| Video | fal | `.txt` | Video URL (text) |

## Implementation

### Helper function in `app.py`

```python
def _cache_artifact(job_id: str, data: bytes | str, ext: str):
    today = datetime.now().strftime("%Y%m%d")
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    cache_dir = os.path.join(".cache", today)
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"{ts}-{job_id}.{ext}")
    mode = "wb" if isinstance(data, bytes) else "w"
    with open(path, mode) as f:
        f.write(data)
    logger.info("Cached artifact | path={}", path)
```

### Call sites (background workers in `app.py`)

1. `_run_image_job` — after success: `_cache_artifact(job_id, data, "png")`
2. `_run_sd_job` — after success: `_cache_artifact(job_id, data, "png")`
3. `_run_video_job` — after success:
   - If `video_data` (bytes): `_cache_artifact(job_id, video_data, "mp4")`
   - If `video_url` only (fal): `_cache_artifact(job_id, video_url, "txt")`

### Error handling

Cache write failure logs a warning but **never fails the job**. The in-memory artifact is the source of truth; cache is a convenience copy.

```python
try:
    _cache_artifact(...)
except Exception:
    logger.warning("Failed to cache artifact | job_id={}", job_id, exc_info=True)
```

### What is NOT in scope

- Cache cleanup / max size / TTL — add when disk pressure is real
- Cache index or listing endpoint — add when browsing is needed
- Deduplication — each job has a unique UUID, no collision possible

## Testing

One test: call `_cache_artifact` with known inputs, verify file exists at the expected path with correct content.
