# Multi-image Upload Support

**Date:** 2026-08-10
**Scope:** DashScope backend (image + video generation), with graceful fallback for other backends
**Status:** Draft

## Problem

Vision models (wan2.7-image, wan2.7-r2v) accept multiple input images, but the web frontend only allows uploading a single image. The entire backend pipeline (`app.py` → service → API) passes a single `image_bytes: bytes | None`.

## Design

### Frontend (`templates/index.html`)

- Change `<input type="file" name="image">` to `<input type="file" name="images" multiple>`.
- Replace the single `<img>` preview with a thumbnail grid (max 10 images).
- Each thumbnail has an × remove button. Removing a thumbnail rebuilds the input's `FileList` via `DataTransfer` API (since `input.files` is read-only).
- At 10 images, display a "max 10 images" hint and disable further selection.
- ~35 lines of vanilla JS. No libraries.

### Translation strings (`translations.py`)

- Update `upload_label`:
  - EN: `"Upload reference images (optional)"`
  - DE: `"Referenzbilder hochladen (optional)"`
- Add new string `upload_max`:
  - EN: `"Maximum 10 images"`
  - DE: `"Maximal 10 Bilder"`

### Backend: `app.py`

- `request.files.get("image")` → `request.files.getlist("images")` → `list[bytes]` (filter empty filenames).
- Pass `images: list[bytes]` to all three background workers (`_run_image_job`, `_run_video_job`, `_run_sd_job`).

### Backend: Service signatures

All three service entry points change their parameter:

| Function | Old | New |
|----------|-----|-----|
| `image_gen.generate_image()` | `image_bytes: bytes \| None` | `images: list[bytes]` |
| `video_gen.start_video_job()` | `image_bytes: bytes \| None` | `images: list[bytes]` |
| `sd_gen.generate_image_sd()` | `image_bytes: bytes \| None` | `images: list[bytes]` |

### Backend: DashScope image generation (`_generate_dashscope`)

Currently builds `content = [{"text": prompt}]` then appends one `{"image": data_uri}`. Change to iterate over all images:

```python
content = [{"text": prompt}]
for img_bytes in images:
    mime = "image/png" if img_bytes[:4] == b'\x89PNG' else "image/jpeg"
    b64 = base64.b64encode(img_bytes).decode()
    content.append({"image": f"data:{mime};base64,{b64}"})
```

Model selection (`model` vs `model_edit`) stays the same: use `model_edit` if any images are present, `model` otherwise.

### Backend: DashScope video generation (`_start_dashscope` / `_build_dashscope_video_payload`)

Currently builds `media = [{"type": "reference_image", "url": data_uri}]` for one image. Change to iterate:

```python
if images:
    media = []
    for img_bytes in images:
        mime = "image/png" if img_bytes[:4] == b'\x89PNG' else "image/jpeg"
        b64 = base64.b64encode(img_bytes).decode()
        media.append({"type": "reference_image", "url": f"data:{mime};base64,{b64}"})
    payload["input"]["media"] = media
```

The `use_media` flag (wan2.6 vs newer models) stays. For wan2.6 (`img_url` format), only the first image is sent (single-image API limitation).

### Backend: Non-DashScope backends

Inside each backend's dispatcher, extract `first = images[0] if images else None` and continue using the existing single-image logic. No API-level changes needed for Azure, OpenAI, fal, or SD.

Specifically:
- `_generate_azure`, `_generate_openai`, `_generate_fal`: extract first image, pass as `image_bytes`.
- `_start_fal`, `_start_azure`: extract first image, pass as `image_bytes`.
- `generate_image_sd`: extract first image, pass as `image_bytes`.

### Testing

- Add a test that verifies multiple images produce multiple `{"image": ...}` entries in the DashScope payload.
- Add a test that verifies non-DashScope backends receive only the first image when multiple are provided.
- Manual test: upload 2+ images via the frontend and verify the thumbnail grid renders correctly with remove functionality.

## Files changed

1. `templates/index.html` — multi-file input, thumbnail grid JS
2. `translations.py` — updated upload label + new max-images string
3. `app.py` — `getlist("images")`, pass `list[bytes]` to workers
4. `services/image_gen.py` — `images: list[bytes]` parameter, DashScope multi-image
5. `services/video_gen.py` — `images: list[bytes]` parameter, DashScope multi-image media[]
6. `services/sd_gen.py` — `images: list[bytes]` parameter, extract first
7. `tests/test_image_gen.py` — multi-image payload test
8. `tests/test_video_gen.py` — multi-image media[] test
9. `tests/test_routes.py` — verify getlist behavior
