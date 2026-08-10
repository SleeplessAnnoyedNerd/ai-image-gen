# Multi-image Upload Support

**Date:** 2026-08-10
**Scope:** DashScope backend (image + video generation), with graceful fallback for other backends
**Status:** Draft (v2 — incorporates DeepSeek review findings)

## Problem

Vision models (wan2.7-image, wan2.7-r2v) accept multiple input images, but the web frontend only allows uploading a single image. The entire backend pipeline (`app.py` → service → API) passes a single `image_bytes: bytes | None`.

## Design

### Frontend (`templates/index.html`)

- Change `<input type="file" name="image">` to `<input type="file" name="images" multiple>`.
- Replace the single `<img>` preview with a thumbnail grid (max 10 images).
- Each thumbnail has an × remove button.
- JS maintains a parallel `selectedFiles: File[]` array. On file input `change`, new files are appended (up to cap). On × click, the file is spliced from the array and the input's `FileList` is rebuilt via `DataTransfer` API (since `input.files` is read-only).
- At 10 images, display a "max 10 images" hint (`<p>` element below the grid, using `{{ t.upload_max }}` via Jinja) and hide the file input.
- ~35 lines of vanilla JS. No libraries.

### Translation strings (`translations.py`)

- Update `upload_label`:
  - EN: `"Upload reference images (optional)"`
  - DE: `"Referenzbilder hochladen (optional)"`
- Add new string `upload_max`:
  - EN: `"Maximum 10 images"`
  - DE: `"Maximal 10 Bilder"`

### Backend: `app.py`

- Read files: `[f.read() for f in request.files.getlist("images") if f.filename]` → `list[bytes]`.
  - Note: `getlist()` returns `list[FileStorage]`, not `list[bytes]`. Must call `.read()` on each.
- **Server-side validation:**
  - File count: `if len(images) > 10: abort(400)` — frontend cap is trivially bypassed via curl.
  - Per-file size: skip any file > 10MB (`len(data) > 10 * 1024 * 1024`). Log a warning for skipped files.
  - Flask config: set `app.config["MAX_CONTENT_LENGTH"] = 120 * 1024 * 1024` (120MB total request cap as defense-in-depth).
- Pass `images: list[bytes]` (always a list, never `None`) to all three background workers.
- When no files are uploaded, pass `[]` (empty list) — not `None`. All downstream code uses `if images:` for truthiness checks.

### Backend: Service signatures

All three service entry points change their parameter from `image_bytes: bytes | None` to `images: list[bytes]`. Always a list, possibly empty.

| Function | Old | New |
|----------|-----|-----|
| `image_gen.generate_image()` | `image_bytes: bytes \| None` | `images: list[bytes]` |
| `video_gen.start_video_job()` | `image_bytes: bytes \| None` | `images: list[bytes]` |
| `sd_gen.generate_image_sd()` | `image_bytes: bytes \| None` | `images: list[bytes]` |

### Backend: Dispatcher branching

Each service's top-level function dispatches to backend-specific implementations. The branching logic:

```python
def generate_image(cfg, prompt, images, model=None, model_edit=None):
    first = images[0] if images else None
    if cfg.image_backend == "dashscope":
        return _generate_dashscope(cfg, prompt, images, model, model_edit)  # full list
    if cfg.image_backend == "fal":
        return _generate_fal(cfg, prompt, first, model, model_edit)        # first only
    if cfg.image_backend == "azure":
        return _generate_azure(cfg, prompt, first, model, model_edit)      # first only
    return _generate_openai(cfg, prompt, first, model, model_edit)         # first only
```

Same pattern for `start_video_job()` — DashScope gets full list, fal/Azure get first image only.
SD's `generate_image_sd()` extracts `first = images[0] if images else None` internally.

### Backend: MIME detection helper

Extract a shared helper to avoid the `[:4]` crash on tiny files and improve MIME detection:

```python
def _mime_and_b64(img_bytes: bytes) -> str:
    """Return data URI string with best-effort MIME detection."""
    if len(img_bytes) >= 4 and img_bytes[:4] == b'\x89PNG':
        mime = "image/png"
    elif len(img_bytes) >= 3 and img_bytes[:3] == b'\xff\xd8\xff':
        mime = "image/jpeg"
    elif len(img_bytes) >= 4 and img_bytes[:4] == b'RIFF' and img_bytes[8:12] == b'WEBP':
        mime = "image/webp"
    elif len(img_bytes) >= 6 and img_bytes[:6] in (b'GIF87a', b'GIF89a'):
        mime = "image/gif"
    else:
        mime = "application/octet-stream"  # let the API decide
    b64 = base64.b64encode(img_bytes).decode()
    return f"data:{mime};base64,{b64}"
```

Place in `services/image_gen.py` (used by DashScope image) and import or duplicate in `services/video_gen.py`.

### Backend: DashScope image generation (`_generate_dashscope`)

Change to accept `images: list[bytes]` and iterate:

```python
active_model = model_edit if images else model
content = [{"text": prompt}]
for img_bytes in images:
    content.append({"image": _mime_and_b64(img_bytes)})
```

### Backend: DashScope video generation (`_start_dashscope` / `_build_dashscope_video_payload`)

Change `_build_dashscope_video_payload` signature from `data_uri: str | None` to `images: list[bytes]`. Handle both format paths internally:

```python
def _build_dashscope_video_payload(model, prompt, images, use_media):
    payload = {
        "model": model,
        "input": {"prompt": prompt},
        "parameters": {"resolution": "720P", "duration": 5, "watermark": False},
    }
    if images:
        if use_media:
            # wan2.7+ models: media[] array supports multiple reference images
            payload["input"]["media"] = [
                {"type": "reference_image", "url": _mime_and_b64(img)} for img in images
            ]
        else:
            # wan2.6 models: img_url format, single image only
            payload["input"]["img_url"] = _mime_and_b64(images[0])
    return payload
```

In `_start_dashscope`: pass `images` directly (no more pre-building `data_uri`), and `use_media = "wan2.6" not in active_model`.

### Backend: Non-DashScope backends

No API-level changes. Each dispatcher extracts `first = images[0] if images else None` and calls existing single-image functions unchanged:
- `_generate_azure`, `_generate_openai`, `_generate_fal`: receive `image_bytes: bytes | None` (first image).
- `_start_fal`, `_start_azure`: receive `image_bytes: bytes | None` (first image).
- `generate_image_sd`: extracts first image internally.

### Testing

- `test_dashscope_multi_image_payload()`: 3 images → payload `content` has 3 `{"image": ...}` entries with correct MIME types.
- `test_dashscope_multi_image_video_media()`: 3 images with wan2.7 model → `media[]` has 3 entries.
- `test_dashscope_video_wan26_single_image()`: 3 images with wan2.6 model → only `img_url` set (first image), no `media[]`.
- `test_non_dashscope_first_image_only()`: Azure/OpenAI/fal receive only `images[0]` when multiple provided.
- `test_zero_images()`: `images=[]` → text-only generation path (no image entries in payload).
- `test_ten_images()`: 10 images → payload has 10 entries (boundary test).
- `test_mixed_mime_types()`: PNG + JPEG + PNG → correct MIME for each.
- `test_server_side_count_limit()`: POST with 11 files → 400 response.
- `test_server_side_size_limit()`: POST with oversized file → file skipped, warning logged.
- `test_empty_file_filtered()`: POST with empty filename entry → ignored.
- Manual test: upload 2+ images via frontend, verify thumbnail grid with remove functionality.

### Memory note

10 × 5MB images → ~50MB raw + ~67MB base64 ≈ ~117MB payload in memory. Acceptable for single-user local app. Add `# ponytail: ~117MB for 10 × 5MB images` comment near encoding loop.

## Files changed

1. `templates/index.html` — multi-file input, thumbnail grid JS, `selectedFiles` array
2. `translations.py` — updated upload label + new `upload_max` string
3. `app.py` — `getlist` + `.read()`, server-side count/size validation, `MAX_CONTENT_LENGTH`
4. `services/image_gen.py` — `images: list[bytes]` parameter, `_mime_and_b64` helper, DashScope multi-image, dispatcher branching
5. `services/video_gen.py` — `images: list[bytes]` parameter, DashScope multi-image `media[]`, updated `_build_dashscope_video_payload`
6. `services/sd_gen.py` — `images: list[bytes]` parameter, extract first
7. `tests/test_image_gen.py` — multi-image, zero-image, mixed-MIME, ten-image tests
8. `tests/test_video_gen.py` — multi-image media[], wan2.6 fallback tests
9. `tests/test_routes.py` — count limit, size limit, empty file filtering, getlist behavior
