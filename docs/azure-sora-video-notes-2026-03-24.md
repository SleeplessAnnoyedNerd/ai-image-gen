# Azure Sora 2 Notes

Date: 2026-03-24

## Context

This project is a Flask-based image/video generator.

Relevant current architecture:
- `app.py` handles request submission, background polling, and result download.
- `services/video_gen.py` contains the video backend integration.
- `.envrc` holds the active Azure OpenAI configuration for video generation.
- `check-sora.sh` is a local helper script for probing and testing the Azure video API.

The active Azure resource in `.envrc` is:
- `VIDEO_API_URL=https://jls.openai.azure.com`
- `VIDEO_BACKEND=azure`
- `VIDEO_MODEL_TEXT=sora-2`
- `VIDEO_MODEL_IMAGE=sora-2`

Secrets are intentionally not copied into this note.

## Main Finding

The current Sora 2 deployment on this Azure resource does not use the older deployment-scoped preview endpoint shape.

Old endpoint shape that returned `404`:
- `/openai/deployments/{deployment}/videos/generations?api-version=2025-04-01-preview`

Working endpoint shape on this resource:
- `POST /openai/v1/videos`
- `GET /openai/v1/videos/{video_id}`
- `GET /openai/v1/videos/{video_id}/content`

Important implication:
- The request uses a `model` field in the JSON body.
- The model/deployment name to send is `sora-2` for the current setup.
- The old `VIDEO_AZURE_PATH` setting is no longer the effective path for the Azure backend implementation.

## Live Checks Performed

The following checks were run against the configured Azure resource after sourcing `.envrc`:

1. `GET /openai/v1/videos?limit=1`
- Returned `200`
- Confirmed the `v1` videos collection exists on this resource.

2. `GET /openai/deployments/sora-2/videos/generations?api-version=2025-04-01-preview`
- Returned `404 Resource not found`
- Confirmed the previous preview-style path is wrong for this deployment.

3. `POST /openai/v1/videos` with `{}`
- Returned `400 Missing required parameter: 'model'.`
- Confirmed the create endpoint exists and expects a `model` body field.

4. `POST /openai/v1/videos/create` with `{}`
- Returned `404`
- Confirmed the create action is not exposed under `/videos/create`.

5. `GET /openai/models?api-version=2024-08-01-preview`
- Confirmed Sora-family models are visible on the resource, including `sora-2`.

## Request Shape

The current implementation now uses this shape for Azure Sora:

```json
{
  "model": "sora-2",
  "prompt": "...",
  "seconds": 4,
  "size": "1280x720"
}
```

For image-to-video, the request adds an input reference using a base64 data URL:

```json
{
  "model": "sora-2",
  "prompt": "...",
  "seconds": 4,
  "size": "1280x720",
  "input_reference": {
    "image_url": "data:image/png;base64,..."
  }
}
```

## Polling Shape

The Azure `v1` video object is treated as asynchronous and polled via:
- `GET /openai/v1/videos/{video_id}`

Relevant fields used by the app:
- `id`
- `status`
- `progress`

Expected status values handled by the code:
- `queued`
- `in_progress`
- `completed`
- `failed`

When the status becomes `completed`, the app downloads the binary video via:
- `GET /openai/v1/videos/{video_id}/content?variant=video`

## Code Changes Made

### `services/video_gen.py`

The Azure backend was updated to:
- submit to `/openai/v1/videos`
- send `model`, `prompt`, `seconds`, `size`
- send image input via `input_reference.image_url`
- poll `/openai/v1/videos/{video_id}`
- download from `/openai/v1/videos/{video_id}/content`

The Azure code now stores and uses `azure_video_id` rather than the previous preview-style job URL.

### `app.py`

Video progress handling was updated so the worker uses:
- `progress` when provided by Azure
- the previous queue-position-based fallback for fal.ai

This avoids mislabeling Azure progress as a queue position.

### `templates/partials/generating.html`

The generating partial now shows:
- percentage progress like `42%` directly
- queued state through the existing queued message
- running state through the existing running message

### `check-sora.sh`

A helper script was added for local validation and manual API checks.

Supported commands:
- `./check-sora.sh probe`
- `./check-sora.sh models`
- `./check-sora.sh videos`
- `./check-sora.sh submit "your prompt"`
- `./check-sora.sh status <video_id>`
- `./check-sora.sh poll <video_id>`

The script:
- auto-sources `.envrc`
- uses `VIDEO_API_URL`, `VIDEO_API_KEY`, and `VIDEO_MODEL_TEXT`
- talks to `/openai/v1/videos`
- uses `seconds` and `size` in the submit payload

Optional overrides:
- `SORA_SECONDS`
- `SORA_SIZE`

## Validation Performed After the Patch

The following checks passed after updating the code:
- Python compile check for `app.py`, `services/video_gen.py`, and `config.py`
- shell syntax check for `check-sora.sh`
- a mocked smoke test covering Azure submit, poll, and binary content download
- live non-destructive `./check-sora.sh probe`

## Known Caveat

The repository test suite is currently stale relative to the latest config shape and video backend behavior.

Examples:
- `tests/conftest.py` still builds `Config` with too few required fields.
- `tests/test_video_gen.py` still assumes the older fal-focused function signatures and response shapes.

So the Azure Sora implementation is now closer to the actual service behavior than the existing tests are.

## Recommended Next Steps

1. Update `tests/conftest.py` to reflect the current `Config` dataclass.
2. Rewrite `tests/test_video_gen.py` to cover both:
   - fal.ai flow
   - Azure Sora `v1` flow
3. Consider making Azure video defaults configurable instead of hardcoded:
   - `seconds`
   - `size`
4. Once ready, run a real `./check-sora.sh submit "..."` test and verify one full end-to-end generation.

## Additional Finding After Live Submit Test

A real submit test was run after fixing the `seconds` field type.

Result:
- The request no longer failed on payload validation.
- It failed because the `model` value is being interpreted as an Azure deployment name, and the provided value does not exist on the target resource.

Observed live error for `sora-2`:

```json
{
  "error": {
    "message": "The API deployment 'sora-2' for this resource does not exist. If you created the deployment within the last 5 minutes, please wait a moment and try again.",
    "type": "video_generation_user_error",
    "param": null,
    "code": null
  }
}
```

Additional live checks were made with other likely Sora-family identifiers:
- `sora-2-2025-10-06`
- `sora`
- `sora-2025-05-02`
- `aoai-sora`
- `aoai-sora-2025-02-28`

All returned the same deployment-not-found error.

### Practical conclusion

The `openai/models` listing on this resource should not be treated as proof that those values are valid callable deployment names for `POST /openai/v1/videos`.

At this point, the remaining blocker is not the endpoint family or payload schema. The remaining blocker is the actual Azure deployment identifier.

The correct next step is to verify the deployment name in Azure AI Foundry or the Azure OpenAI deployment list for the exact resource behind:
- `https://jls.openai.azure.com`

Once the real deployment name is known, it should replace:
- `VIDEO_MODEL_TEXT`
- `VIDEO_MODEL_IMAGE`

in `.envrc`.
