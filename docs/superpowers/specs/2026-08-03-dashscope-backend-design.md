# DashScope (Alibaba Cloud) Backend Design

**Date:** 2026-08-03
**Status:** Approved (revised after DeepSeek review round 2)

## Goal

Add Alibaba Cloud DashScope as a new backend for both image and video generation.
Models: `wan2.7-image` / `wan2.7-image-pro` (image), `happyhorse-1.1-t2v` (text-to-video), `happyhorse-1.1-r2v` (reference-to-video).

## Constraints

- Single backend active at a time via env vars (same as today — no multi-provider UI).
- Only configure models for the active backend in `.envrc`. No model-to-backend routing.
- Two URL endpoints exist (pay-as-you-go vs subscription) but only one is active at a time. User sets it in `.envrc`.

## Configuration

New env vars in `.envrc`:

```bash
IMAGE_BACKEND=dashscope
VIDEO_BACKEND=dashscope
DASHSCOPE_API_KEY=sk-xxxx
DASHSCOPE_API_URL=https://<workspace-id>.cn-beijing.maas.aliyuncs.com
IMAGE_MODEL=wan2.7-image,wan2.7-image-pro
IMAGE_MODEL_EDIT=wan2.7-image-pro
VIDEO_MODEL_IMAGE=happyhorse-1.1-r2v      # used when image is uploaded (reference-to-video)
VIDEO_MODEL_TEXT=happyhorse-1.1-t2v       # used when no image (text-to-video)
```

`DASHSCOPE_API_URL` is the workspace base URL (no path suffix). Backend functions append the correct API path.

**Note on config approach:** Unlike fal/azure/openai backends that reuse `image_api_url`/`image_api_key`, the dashscope backend reads from dedicated `dashscope_api_url`/`dashscope_api_key` fields. This is a deliberate divergence — DashScope uses a single workspace URL with different API paths per service, rather than a single endpoint URL per service.

### Config changes (`config.py`)

Two new optional fields on `Config`:

```python
dashscope_api_url: str   # empty string = not configured
dashscope_api_key: str   # empty string = not configured
```

Read via `os.environ.get()` (not `_require()`). Only needed when backend is `dashscope`.

### Existing config fields — make optional for dashscope backend

**Critical fix (DeepSeek review round 2):** The current `Config.from_env()` uses `_require()` for `IMAGE_API_URL`, `IMAGE_API_KEY`, `VIDEO_API_URL`, `VIDEO_API_KEY`. When the backend is `dashscope`, these env vars won't be set and the app crashes on startup.

**Fix:** Change these four fields from `_require()` to `os.environ.get(..., "")` — same pattern as `sd_api_url` already uses. The dashscope backend reads from `dashscope_api_url`/`dashscope_api_key` instead, so the empty fallbacks are harmless.

### Image content block format — verify during implementation

**Note (DeepSeek review round 2):** The spec uses `{"text": "..."}` / `{"image": "..."}` content blocks. Some multimodal APIs use `{"type": "text", "text": "..."}` / `{"type": "image_url", "image_url": {"url": "..."}}` instead. Verify against DashScope docs during implementation and adjust if needed.

## Image Generation (`services/image_gen.py`)

Add `dashscope` branch to `generate_image()` dispatcher. New function `_generate_dashscope()`.

### API

```
POST {DASHSCOPE_API_URL}/api/v1/services/aigc/multimodal-generation/generation
Authorization: Bearer {DASHSCOPE_API_KEY}
Content-Type: application/json
```

**Sync mode** (no `X-DashScope-Async` header) — image generation is fast enough.

Request body (text-only, no reference image):

```json
{
  "model": "wan2.7-image-pro",
  "input": {
    "messages": [{
      "role": "user",
      "content": [
        {"text": "a cat wearing a hat"}
      ]
    }]
  },
  "parameters": {
    "size": "1K",
    "n": 1
  }
}
```

Request body (with reference image — edit path):

```json
{
  "model": "wan2.7-image-pro",
  "input": {
    "messages": [{
      "role": "user",
      "content": [
        {"text": "make the cat wear a red hat"},
        {"image": "data:image/png;base64,iVBOR..."}
      ]
    }]
  },
  "parameters": {
    "size": "1K",
    "n": 1
  }
}
```

**Size parameter:** Use resolution keywords `"1K"`, `"2K"`, `"4K"` (or explicit `"W*H"` format). Default `"1K"`.

**MIME detection:** Detect from magic bytes (`image_bytes[:4] == b'\x89PNG'` → `image/png`, else `image/jpeg`).

### Response format

```json
{
  "output": {
    "choices": [{
      "finish_reason": "stop",
      "message": {
        "content": [
          {"type": "image", "image": "https://..."}
        ]
      }
    }]
  },
  "usage": { ... },
  "request_id": "..."
}
```

Parse: `response["output"]["choices"][0]["message"]["content"]` → find item where `type == "image"` → extract `.image` URL → download → return bytes.

### Flow

1. Build payload with `messages[]` structure. If `image_bytes` is provided, add `{"image": "data:{mime};base64,..."}` to the content array (edit path, uses `model_edit`).
2. POST to endpoint (sync — no async header).
3. Parse response: extract image URL from `output.choices[0].message.content[]`.
4. Download image, return bytes.

### Error handling

- Missing `dashscope_api_url` or `dashscope_api_key` → raise `ValueError` with clear message.
- API errors → raise with response body for debugging.
- If response has no image in `content[]` → raise `RuntimeError`.

## Video Generation (`services/video_gen.py`)

Add `dashscope` branch to `start_video_job()` / `poll_video_job()`. New functions `_start_dashscope()` and `_poll_dashscope()`.

### API

```
POST {DASHSCOPE_API_URL}/api/v1/services/aigc/video-generation/video-synthesis
Authorization: Bearer {DASHSCOPE_API_KEY}
Content-Type: application/json
X-DashScope-Async: enable
```

Request body (text-to-video, using `happyhorse-1.1-t2v`):

```json
{
  "model": "happyhorse-1.1-t2v",
  "input": {
    "prompt": "a cat walking in a garden"
  },
  "parameters": {
    "resolution": "720P",
    "duration": 5,
    "watermark": false
  }
}
```

Request body (reference-to-video, using `happyhorse-1.1-r2v`):

```json
{
  "model": "happyhorse-1.1-r2v",
  "input": {
    "prompt": "a cat walking in a garden",
    "media": [
      {"type": "reference_image", "url": "data:image/png;base64,iVBOR..."}
    ]
  },
  "parameters": {
    "resolution": "720P",
    "duration": 5,
    "watermark": false
  }
}
```

**Model selection:** `happyhorse-1.1-r2v` when `image_bytes` is provided, `happyhorse-1.1-t2v` when not. This maps to the existing `VIDEO_MODEL_IMAGE` / `VIDEO_MODEL_TEXT` config split.

**Parameters:**
- `resolution`: `"720P"` (uppercase P)
- `duration`: seconds (5)
- `watermark`: `false` to disable the default AI-generated watermark

### Response (submit)

```json
{
  "output": {
    "task_id": "task-xxxx",
    "task_status": "PENDING"
  },
  "request_id": "..."
}
```

### Response (poll — `GET /api/v1/tasks/{task_id}`)

```json
{
  "output": {
    "task_id": "task-xxxx",
    "task_status": "SUCCEEDED",
    "video_url": "https://..."
  }
}
```

### Flow

**`_start_dashscope()`:**
1. Build payload with prompt and optional `media[]` array for reference image.
2. POST to submit endpoint (with `X-DashScope-Async: enable` header).
3. Return `{"task_id": data["output"]["task_id"]}`.

**`_poll_dashscope()`:**
1. GET `/api/v1/tasks/{task_id}` with `Authorization: Bearer {key}`.
2. Map `output.task_status`:
   - `SUCCEEDED` → extract `output.video_url`, download video, return `{"status": "done", "video_data": bytes}`.
   - `PENDING` / `RUNNING` → return `{"status": "pending", "queue_position": None}`.
   - `FAILED` → return `{"status": "error", "message": "..."}`.
   - `CANCELED` / `UNKNOWN` → return `{"status": "error", "message": "Task was canceled or expired"}`.

### Integration with existing polling loop

The existing `_run_video_job()` in `app.py` calls `start_video_job()` then loops on `poll_video_job()` every 2 seconds for up to 120 iterations (4 minutes). This is backend-agnostic — no changes needed in `app.py`.

## Files Changed

| File | Change |
|------|--------|
| `config.py` | Add `dashscope_api_url`, `dashscope_api_key` fields; make `image_api_url`/`image_api_key`/`video_api_url`/`video_api_key` optional (default `""`) |
| `services/image_gen.py` | Add `dashscope` branch + `_generate_dashscope()` |
| `services/video_gen.py` | Add `dashscope` branch + `_start_dashscope()`, `_poll_dashscope()` |
| `.envrc` | Add commented-out DashScope config example |

No changes to `app.py`, templates, or UI.

## Testing

1. Set `IMAGE_BACKEND=dashscope`, `VIDEO_BACKEND=dashscope` with valid API key/URL.
2. Generate an image with `wan2.7-image` (text-only prompt).
3. Generate an image with `wan2.7-image-pro` + reference image upload.
4. Generate a video with `happyhorse-1.1-t2v` (text-only, no image upload).
5. Generate a video with `happyhorse-1.1-r2v` + reference image upload.
6. Verify error handling: invalid API key, missing config, timeout.
7. Verify no watermark on output videos.
