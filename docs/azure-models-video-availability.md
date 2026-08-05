# Azure OpenAI — Model List & Video Generation Availability

**Resource:** `https://jls.openai.azure.com`  
**Total models in catalog:** 161

## Method

Every model was probed with:
```
POST /openai/deployments/{model}/videos/generations?api-version=2025-04-01-preview
```
Result: **all 161 models returned 404 Resource Not Found** — the video generation
API is not provisioned on this resource for any model.

## Video / Sora

| Model ID | Chat | Compl. | Embed | Infer | Video probe |
|----------|:----:|:------:|:-----:|:-----:|-------------|
| `aoai-sora-2025-02-28` |  |  |  | ✓ | ❌ DeploymentNotFound |
| `sora-2025-05-02` |  |  |  | ✓ | ❌ DeploymentNotFound |
| `sora-2-2025-10-06` |  |  |  | ✓ | ❌ DeploymentNotFound |
| `aoai-sora` |  |  |  | ✓ | ❌ DeploymentNotFound |
| `sora` |  |  |  | ✓ | ❌ DeploymentNotFound |
| `sora-2` |  |  |  | ✓ | ❌ DeploymentNotFound |

## Image Generation

| Model ID | Chat | Compl. | Embed | Infer | Video probe |
|----------|:----:|:------:|:-----:|:-----:|-------------|
| `dall-e-3-3.0` |  |  |  | ✓ | — |
| `dall-e-2-2.0` |  |  |  | ✓ | — |
| `gpt-image-1-2025-04-15` |  |  |  | ✓ | — |
| `gpt-image-1-mini-2025-10-06` |  |  |  | ✓ | — |
| `gpt-image-1.5-2025-12-16` |  |  |  | ✓ | — |
| `dall-e-3` |  |  |  | ✓ | — |
| `dall-e-2` |  |  |  | ✓ | — |
| `gpt-image-1` |  |  |  | ✓ | — |
| `gpt-image-1-mini` |  |  |  | ✓ | — |
| `gpt-image-1.5` |  |  |  | ✓ | — |

## Chat / Completion

| Model ID | Chat | Compl. | Embed | Infer | Video probe |
|----------|:----:|:------:|:-----:|:-----:|-------------|
| `gpt-4-0125-Preview` | ✓ |  |  | ✓ | — |
| `gpt-4-1106-Preview` | ✓ |  |  | ✓ | — |
| `gpt-4-0314` | ✓ |  |  | ✓ | — |
| `gpt-4-0613` | ✓ |  |  | ✓ | — |
| `gpt-4-32k-0314` | ✓ |  |  | ✓ | — |
| `gpt-4-32k-0613` | ✓ |  |  | ✓ | — |
| `gpt-4-vision-preview` | ✓ |  |  | ✓ | — |
| `gpt-4-turbo-2024-04-09` | ✓ |  |  | ✓ | — |
| `gpt-4-turbo-jp` | ✓ |  |  | ✓ | — |
| `gpt-4o-2024-05-13` | ✓ |  |  | ✓ | — |
| `gpt-4o-2024-08-06` | ✓ |  |  | ✓ | — |
| `gpt-4o-mini-2024-07-18` | ✓ |  |  | ✓ | — |
| `gpt-4o-2024-11-20` | ✓ |  |  | ✓ | — |
| `gpt-4o-audio-mai` | ✓ |  |  | ✓ | — |
| `gpt-4o-realtime-preview` |  |  |  | ✓ | — |
| `gpt-4o-mini-realtime-preview-2024-12-17` |  |  |  | ✓ | — |
| `gpt-4o-realtime-preview-2024-12-17` |  |  |  | ✓ | — |
| `gpt-4o-realtime-preview-2025-06-03` |  |  |  | ✓ | — |
| `gpt-4o-canvas-2024-09-25` | ✓ |  |  | ✓ | — |
| `gpt-4o-audio-preview-2024-10-01` | ✓ |  |  | ✓ | — |
| `gpt-4o-audio-preview-2024-12-17` | ✓ |  |  | ✓ | — |
| `gpt-4o-audio-preview-2025-06-03` | ✓ |  |  | ✓ | — |
| `gpt-4o-mini-audio-preview-2024-12-17` | ✓ |  |  | ✓ | — |
| `computer-use-preview-2025-04-15` | ✓ | ✓ |  | ✓ | — |
| `gpt-4o-transcribe-2025-03-20` |  |  |  | ✓ | — |
| `gpt-4o-mini-transcribe-2025-03-20` |  |  |  | ✓ | — |
| `gpt-4o-mini-tts-2025-03-20` |  |  |  | ✓ | — |
| `gpt-35-turbo-0301` | ✓ | ✓ |  | ✓ | — |
| `gpt-35-turbo-0613` | ✓ |  |  | ✓ | — |
| `gpt-35-turbo-1106` | ✓ |  |  | ✓ | — |
| `gpt-35-turbo-0125` | ✓ |  |  | ✓ | — |
| `gpt-35-turbo-instruct-0914` |  | ✓ |  | ✓ | — |
| `gpt-35-turbo-16k-0613` | ✓ |  |  | ✓ | — |
| `o1-mini-2024-09-12` | ✓ |  |  | ✓ | — |
| `o1-2024-12-17` | ✓ |  |  | ✓ | — |
| `o1-pro-2025-03-19` |  |  |  | ✓ | — |
| `o3-mini-alpha-2024-12-17` | ✓ |  |  | ✓ | — |
| `o3-mini-2025-01-31` | ✓ |  |  | ✓ | — |
| `o3-2025-04-16` | ✓ |  |  | ✓ | — |
| `o3-pro-2025-06-10` |  |  |  | ✓ | — |
| `o3-deep-research-2025-06-26` | ✓ |  |  | ✓ | — |
| `o3-deep-research-2025-06-26-ev3` | ✓ |  |  | ✓ | — |
| `model-router-2025-05-19` | ✓ |  |  | ✓ | — |
| `model-router-2025-08-07` | ✓ |  |  | ✓ | — |
| `model-router-2025-11-18` | ✓ |  |  | ✓ | — |
| `codex-mini-2025-05-16` |  |  |  | ✓ | — |
| `o4-mini-2025-04-16` | ✓ |  |  | ✓ | — |
| `gpt-4.1-2025-04-14` | ✓ |  |  | ✓ | — |
| `gpt-4.1-2025-04-14-text` | ✓ |  |  | ✓ | — |
| `gpt-4.1-mini-2025-04-14` | ✓ |  |  | ✓ | — |
| `gpt-4.1-nano-2025-04-14` | ✓ |  |  | ✓ | — |
| `gpt-5-2025-08-07` | ✓ |  |  | ✓ | — |
| `gpt-5-nano-2025-08-07` | ✓ |  |  | ✓ | — |
| `gpt-5-mini-2025-08-07` | ✓ |  |  | ✓ | — |
| `gpt-5-chat-2025-08-07` | ✓ |  |  | ✓ | — |
| `gpt-5-chat-2025-08-15` | ✓ |  |  | ✓ | — |
| `gpt-5-codex-2025-09-15` |  |  |  | ✓ | — |
| `gpt-5-chat-2025-10-03` | ✓ |  |  | ✓ | — |
| `gpt-5-pro-2025-10-06` |  |  |  | ✓ | — |
| `gpt-4o-transcribe-diarize-2025-10-15` |  |  |  | ✓ | — |
| `gpt-5.1-chat-2025-11-13` | ✓ |  |  | ✓ | — |
| `gpt-5.1-2025-11-13` | ✓ |  |  | ✓ | — |
| `gpt-5.1-codex-mini-2025-11-13` |  |  |  | ✓ | — |
| `gpt-5.1-codex-2025-11-13` |  |  |  | ✓ | — |
| `gpt-5.1-codex-max-2025-12-04` |  |  |  | ✓ | — |
| `gpt-5.2-2025-12-11` | ✓ |  |  | ✓ | — |
| `gpt-5.2-chat-2025-12-11` | ✓ |  |  | ✓ | — |
| `gpt-4o-mini-transcribe-2025-12-15` |  |  |  | ✓ | — |
| `gpt-4o-mini-tts-2025-12-15` |  |  |  | ✓ | — |
| `gpt-5-mini-lite-2025-08-07` | ✓ |  |  | ✓ | — |
| `gpt-5.2-codex-2026-01-14` |  |  |  | ✓ | — |
| `gpt-5.2-chat-2026-02-10` | ✓ |  |  | ✓ | — |
| `gpt-5.3-codex-2026-02-20` |  |  |  | ✓ | — |
| `gpt-5.3-codex-2026-02-24` |  |  |  | ✓ | — |
| `gpt-5.4-2026-03-05` | ✓ |  |  | ✓ | — |
| `gpt-5.3-chat-2026-03-03` | ✓ |  |  | ✓ | — |
| `gpt-5.4-pro-2026-03-05` |  |  |  | ✓ | — |
| `gpt-5.4-mini-2026-03-17` | ✓ |  |  | ✓ | — |
| `gpt-5.4-nano-2026-03-17` | ✓ |  |  | ✓ | — |
| `gpt-4` | ✓ |  |  | ✓ | — |
| `gpt-4-32k` | ✓ |  |  | ✓ | — |
| `gpt-4o` | ✓ |  |  | ✓ | — |
| `gpt-4o-mini` | ✓ |  |  | ✓ | — |
| `gpt-4o-transcribe` |  |  |  | ✓ | — |
| `gpt-35-turbo` | ✓ |  |  | ✓ | — |
| `gpt-35-turbo-instruct` |  | ✓ |  | ✓ | — |
| `gpt-35-turbo-16k` | ✓ |  |  | ✓ | — |
| `o1-pro` |  |  |  | ✓ | — |
| `o3-mini-alpha` | ✓ |  |  | ✓ | — |
| `o3-mini` | ✓ |  |  | ✓ | — |
| `o3` | ✓ |  |  | ✓ | — |
| `o3-pro` |  |  |  | ✓ | — |
| `model-router` | ✓ |  |  | ✓ | — |
| `o4-mini` | ✓ |  |  | ✓ | — |
| `gpt-4.1` | ✓ |  |  | ✓ | — |
| `gpt-4.1-mini` | ✓ |  |  | ✓ | — |
| `gpt-4.1-nano` | ✓ |  |  | ✓ | — |
| `gpt-4o-transcribe-diarize` |  |  |  | ✓ | — |
| `gpt-5.1` | ✓ |  |  | ✓ | — |
| `gpt-4o-mini-transcribe` |  |  |  | ✓ | — |
| `gpt-4o-mini-tts` |  |  |  | ✓ | — |

## Embeddings

| Model ID | Chat | Compl. | Embed | Infer | Video probe |
|----------|:----:|:------:|:-----:|:-----:|-------------|
| `text-similarity-babbage-001` |  |  | ✓ |  | — |
| `text-search-babbage-doc-001` |  |  | ✓ |  | — |
| `text-search-babbage-query-001` |  |  | ✓ |  | — |
| `code-search-babbage-code-001` |  |  | ✓ |  | — |
| `code-search-babbage-text-001` |  |  | ✓ |  | — |
| `text-similarity-curie-001` |  |  | ✓ |  | — |
| `text-search-curie-doc-001` |  |  | ✓ |  | — |
| `text-search-curie-query-001` |  |  | ✓ |  | — |
| `text-similarity-davinci-001` |  |  | ✓ |  | — |
| `text-search-davinci-doc-001` |  |  | ✓ |  | — |
| `text-search-davinci-query-001` |  |  | ✓ |  | — |
| `text-similarity-ada-001` |  |  | ✓ |  | — |
| `text-search-ada-doc-001` |  |  | ✓ |  | — |
| `text-search-ada-query-001` |  |  | ✓ |  | — |
| `code-search-ada-code-001` |  |  | ✓ |  | — |
| `code-search-ada-text-001` |  |  | ✓ |  | — |
| `text-embedding-ada-002` |  |  | ✓ | ✓ | — |
| `text-embedding-ada-002-2` |  |  | ✓ | ✓ | — |
| `text-embedding-3-small` |  |  | ✓ | ✓ | — |
| `text-embedding-3-large` |  |  | ✓ | ✓ | — |
| `o3-deep-research-2025-06-26` | ✓ |  |  | ✓ | — |
| `o3-deep-research-2025-06-26-ev3` | ✓ |  |  | ✓ | — |
| `text-embedding-ada-002` |  |  | ✓ | ✓ | — |

## Audio / Speech

| Model ID | Chat | Compl. | Embed | Infer | Video probe |
|----------|:----:|:------:|:-----:|:-----:|-------------|
| `tts-001` |  |  |  | ✓ | — |
| `tts-hd-001` |  |  |  | ✓ | — |
| `whisper-001` |  |  |  | ✓ | — |
| `gpt-4o-audio-mai` | ✓ |  |  | ✓ | — |
| `gpt-4o-realtime-preview` |  |  |  | ✓ | — |
| `gpt-4o-mini-realtime-preview-2024-12-17` |  |  |  | ✓ | — |
| `gpt-4o-realtime-preview-2024-12-17` |  |  |  | ✓ | — |
| `gpt-4o-realtime-preview-2025-06-03` |  |  |  | ✓ | — |
| `gpt-4o-audio-preview-2024-10-01` | ✓ |  |  | ✓ | — |
| `gpt-4o-audio-preview-2024-12-17` | ✓ |  |  | ✓ | — |
| `gpt-4o-audio-preview-2025-06-03` | ✓ |  |  | ✓ | — |
| `gpt-4o-mini-audio-preview-2024-12-17` | ✓ |  |  | ✓ | — |
| `gpt-4o-transcribe-2025-03-20` |  |  |  | ✓ | — |
| `gpt-4o-mini-transcribe-2025-03-20` |  |  |  | ✓ | — |
| `gpt-4o-mini-tts-2025-03-20` |  |  |  | ✓ | — |
| `gpt-audio-2025-08-28` | ✓ |  |  | ✓ | — |
| `gpt-realtime-2025-08-28` |  |  |  | ✓ | — |
| `gpt-audio-mini-2025-10-06` | ✓ |  |  | ✓ | — |
| `gpt-realtime-mini-2025-10-06` |  |  |  | ✓ | — |
| `gpt-4o-transcribe-diarize-2025-10-15` |  |  |  | ✓ | — |
| `gpt-4o-mini-transcribe-2025-12-15` |  |  |  | ✓ | — |
| `gpt-4o-mini-tts-2025-12-15` |  |  |  | ✓ | — |
| `gpt-realtime-mini-2025-12-15` |  |  |  | ✓ | — |
| `gpt-audio-mini-2025-12-15` | ✓ |  |  | ✓ | — |
| `gpt-audio-1.5-2026-02-23` | ✓ |  |  | ✓ | — |
| `gpt-realtime-1.5-2026-02-23` |  |  |  | ✓ | — |
| `tts` |  |  |  | ✓ | — |
| `tts-hd` |  |  |  | ✓ | — |
| `whisper` |  |  |  | ✓ | — |
| `gpt-4o-transcribe` |  |  |  | ✓ | — |
| `gpt-4o-transcribe-diarize` |  |  |  | ✓ | — |
| `gpt-4o-mini-transcribe` |  |  |  | ✓ | — |
| `gpt-4o-mini-tts` |  |  |  | ✓ | — |
| `gpt-realtime-mini` |  |  |  | ✓ | — |
| `gpt-audio-mini` | ✓ |  |  | ✓ | — |

## Other / Legacy

| Model ID | Infer |
|----------|:-----:|
| `babbage` |  |
| `babbage-002` | ✓ |
| `curie` |  |
| `davinci` |  |
| `davinci-002` | ✓ |
| `text-davinci-003` |  |
| `ada` |  |

## Conclusion

None of the models on this Azure OpenAI resource are available for video generation via the REST API.
The Sora models (`sora`, `sora-2`, `aoai-sora`, etc.) appear in the global model catalog
but return `DeploymentNotFound` — meaning a deployment for them has not been created in this resource.

To enable Azure Sora video generation, an administrator must:
1. Open the Azure portal → Azure OpenAI → `jls` resource
2. Go to **Deployments** → **Create new deployment**
3. Select the `sora-2` base model and give it a deployment name
4. Set `VIDEO_MODEL_IMAGE` / `VIDEO_MODEL_TEXT` in `.envrc` to that deployment name
