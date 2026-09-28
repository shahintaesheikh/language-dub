---
name: seed-audio-api
description: BytePlus Seed Audio 1.0 API calling convention and best practices
---

# Seed Audio 1.0 API — BytePlus Skill

A concise reference for calling the BytePlus Seed Audio 1.0 HTTP API: endpoints, auth, request/response shapes, and best practices.

---

## Quick Facts

| Item | Value |
|---|---|
| Endpoint | `POST https://voice.ap-southeast-1.bytepluses.com/api/v3/tts/create` |
| Auth header | `X-Api-Key` |
| Request ID header | `X-Api-Request-Id` (UUID, client-generated) |
| Model ID | `seed-audio-1.0` |
| Content type | `application/json` |
| Max output | 120 seconds per call |
| Max prompt | 3,000 characters |
| Reference audio | up to 3 clips, each ≤ 30 s / ≤ 10 MB (wav/mp3/pcm/ogg_opus) |
| Reference image | 1 image, ≤ 10 MB (jpeg/png/webp) |
| Synchronous | Yes (block until done; set `--max-time 120`) |

---

## Request

### Headers

```
Content-Type: application/json
X-Api-Key: <your_api_key>
X-Api-Request-Id: <random_uuid>
```

### Body Schema

```json
{
  "model": "seed-audio-1.0",
  "text_prompt": "<string, required, 1-3000 chars>",
  "references": [
    {
      "audio_url": "<url of reference audio>",
      "speaker": "<voice id — TTS 2.0 or cloned>",
      "audio_data": "<base64 audio>",
      "image_url": "<url of reference image>",
      "image_data": "<base64 image>"
    }
  ],
  "audio_config": {
    "format": "wav",
    "sample_rate": 24000,
    "speech_rate": 0,
    "loudness_rate": 0,
    "pitch_rate": 0,
    "enable_subtitle": false
  },
  "watermark": {
    "aigc_watermark": false,
    "aigc_metadata": {
      "enable": false,
      "content_producer": "",
      "produce_id": "",
      "content_propagator": "",
      "propagate_id": ""
    }
  }
}
```

### Body Parameters

| Field | Type | Default | Notes |
|---|---|---|---|
| `model` | string | — | **Required.** Must be `seed-audio-1.0`. |
| `text_prompt` | string | — | **Required.** 1–3,000 chars. Use `@Audio1`…`@Audio3` to reference audio clips by position in `references`. |
| `references` | array | — | Omit for text-only. Up to 3 audio refs or 1 image ref. Audio and image refs cannot be mixed. |
| `references[].audio_url` | string | — | Remote URL of reference audio. Use one of: `audio_url`, `audio_data`, or `speaker`. |
| `references[].audio_data` | string | — | Base64-encoded reference audio. |
| `references[].speaker` | string | — | Voice ID (Doubao TTS 2.0 or cloned voice). |
| `references[].image_url` | string | — | Remote URL of reference image. Use one of: `image_url` or `image_data`. |
| `references[].image_data` | string | — | Base64-encoded reference image. |
| `audio_config.format` | string | `wav` | `wav`, `mp3`, `pcm`, `ogg_opus`. |
| `audio_config.sample_rate` | int | varies | `8000`, `16000`, `24000`, `32000`, `44100`, `48000`. Default: wav/pcm → 24000; mp3 → 44100. |
| `audio_config.speech_rate` | int | `0` | `-50` (0.5×) to `100` (2.0×). |
| `audio_config.loudness_rate` | int | `0` | `-50` (0.5×) to `100` (2.0×). |
| `audio_config.pitch_rate` | int | `0` | `-12` to `12`. |
| `audio_config.enable_subtitle` | bool | `false` | Return word- and sentence-level timestamps. |
| `watermark` | object | `{}` | Watermark config. Empty object = no watermarks. |
| `watermark.aigc_watermark` | bool | `false` | Explicit audio rhythm marker at end. |
| `watermark.aigc_metadata.enable` | bool | `false` | Implicit metadata watermark in header. |

---

## Response

```json
{
  "code": 200,
  "message": "success",
  "audio": "<base64 encoded audio bytes>",
  "duration": 12.34,
  "original_duration": 12.34,
  "url": "https://...",
  "subtitle": {
    "text": "Hello. Stay close.",
    "sentences": [
      {
        "start_time": 0,
        "end_time": 1800,
        "text": "Hello.",
        "words": [
          { "start_time": 0, "end_time": 600, "text": "Hello" }
        ]
      }
    ]
  }
}
```

| Field | Type | Notes |
|---|---|---|
| `code` | int | Status code. Non-zero = error. |
| `message` | string | Status / error message. |
| `audio` | string | Base64-encoded audio. |
| `duration` | float | Post-processed duration (seconds). |
| `original_duration` | float | Model's original duration (seconds). Used for billing; capped at 120s. |
| `url` | string | Temporary audio URL, valid for 2 hours. |
| `subtitle` | object | Present only when `enable_subtitle: true`. |
| `subtitle.text` | string | Full subtitle text. |
| `subtitle.sentences[]` | array | Utterance-level timestamps (ms). |
| `subtitle.words[]` | array | Word-level timestamps (ms). |

Response header `X-Tt-Logid` — log this for troubleshooting.

---

## Examples

### 1. Text-only (T2A)

```bash
curl --request POST \
  --url 'https://voice.ap-southeast-1.bytepluses.com/api/v3/tts/create' \
  --max-time 120 \
  --header 'Content-Type: application/json' \
  --header 'X-Api-Key: your_api_key' \
  --header 'X-Api-Request-Id: <uuid>' \
  --data '{
    "model": "seed-audio-1.0",
    "text_prompt": "Inside a football stadium, the crowd erupts as the commentator shouts: \"What a goal!\"",
    "audio_config": {
      "format": "wav",
      "sample_rate": 24000
    }
  }'
```

### 2. Voice cloning (TA2A) with reference audio

```bash
curl --request POST \
  --url 'https://voice.ap-southeast-1.bytepluses.com/api/v3/tts/create' \
  --max-time 120 \
  --header 'Content-Type: application/json' \
  --header 'X-Api-Key: your_api_key' \
  --header 'X-Api-Request-Id: <uuid>' \
  --data '{
    "model": "seed-audio-1.0",
    "text_prompt": "@Audio1 Say this in the same voice, calm and reassuring: \"Welcome to the team, we'\''re glad you'\''re here.\"",
    "references": [
      { "audio_url": "https://example.com/reference-voice.wav" }
    ],
    "audio_config": {
      "format": "mp3",
      "sample_rate": 44100,
      "enable_subtitle": true
    }
  }'
```

### 3. Multi-voice (3 references)

```json
{
  "model": "seed-audio-1.0",
  "text_prompt": "@Audio1 \"Did you bring the keys?\" @Audio2 \"Right here.\" @Audio3 (sigh) \"Let'\''s go then.\"",
  "references": [
    { "audio_url": "https://.../voice1.wav" },
    { "audio_url": "https://.../voice2.wav" },
    { "audio_url": "https://.../voice3.wav" }
  ],
  "audio_config": { "format": "wav", "sample_rate": 24000 }
}
```

### 4. Python

```python
import base64
import json
import uuid
import urllib.request

API_KEY = "your_api_key"
URL = "https://voice.ap-southeast-1.bytepluses.com/api/v3/tts/create"

payload = {
    "model": "seed-audio-1.0",
    "text_prompt": "A warm male narrator voice, slow pace: \"In the beginning, there was silence.\"",
    "audio_config": {"format": "wav", "sample_rate": 24000},
}

req = urllib.request.Request(
    URL,
    data=json.dumps(payload).encode(),
    headers={
        "Content-Type": "application/json",
        "X-Api-Key": API_KEY,
        "X-Api-Request-Id": str(uuid.uuid4()),
    },
    method="POST",
)

with urllib.request.urlopen(req, timeout=130) as resp:
    result = json.loads(resp.read())
    if result.get("code") == 200:
        with open("output.wav", "wb") as f:
            f.write(base64.b64decode(result["audio"]))
        print("Saved output.wav, duration:", result["duration"])
    else:
        print("Error:", result)
```

---

## Best Practices

### Authentication
- Store `X-Api-Key` in environment variables, never in code or client-side code.
- Use a **server-side proxy** if calling from a browser to avoid exposing the key.

### Request IDs
- Always send a unique `X-Api-Request-Id` (UUID v4).
- Log the returned `X-Tt-Logid` response header for support / debugging.

### Reference Audio
- **One of** `audio_url`, `audio_data`, or `speaker` per reference entry — never mix.
- Prefer `audio_url` for references > ~5 MB; `audio_data` (base64) inflates payload size by ~33%.
- Keep clips **clean**: single speaker, no background music, clear recording.
- 10–30 seconds of clear speech gives the best clone quality.
- Reference order in `references` matches `@Audio1`, `@Audio2`, `@Audio3` in the prompt.

### Reference Images
- Cannot be combined with audio references in the same request.
- Use `image_url` or `image_data`, not both.

### Prompting
- Up to 3,000 chars. Be descriptive: speaker, emotion, pace, environment, sound effects.
- For voice cloning, start with `@Audio1` and state the voice direction clearly.
- Use punctuation (commas, periods, em dashes) to control pauses and rhythm.

### Audio Output
- Match `sample_rate` to your downstream pipeline to avoid resampling artifacts.
- Use `wav` for lossless quality, `mp3` for smaller file sizes.
- `enable_subtitle: true` returns word-level timestamps — useful for lip-sync and alignment.

### Duration / Pace Control
- `speech_rate` range: `-50` to `100` (0.5× – 2.0× speed).
- For natural-sounding speed adjustments, stay within ±20 (`-20` to `20`).
- Fine-tune with the prompt (add/remove filler words) before pushing `speech_rate` to extremes.

### Error Handling
- Check `code` in the response body — non-200 means failure.
- `original_duration` is what you're billed on; `duration` is after speed/post-processing.
- Set request timeout to ≥ 130 seconds (model can take up to 120s for long outputs).

### Long-form Audio
- Max 120 seconds per call. For longer content, split at natural pauses and stitch.
- Use the same reference clip and consistent prompt headers across chunks to keep voice stable.

---

## Common Error Scenarios

| Symptom | Likely Cause | Fix |
|---|---|---|
| 401 / auth error | Wrong or missing `X-Api-Key` | Verify key from BytePlus Console |
| 400 / validation fail | Missing `model`, invalid field, mixed audio+image refs | Check schema; ensure one ref type per entry |
| 413 payload too large | Base64 reference exceeds size limit | Use `audio_url`/`image_url` instead of inline data |
| Voice doesn't match | No `@Audio1` tag in prompt, or reference is noisy | Add `@Audio1` tag; use clean reference clip |
| Output too short/long | Prompt length or speech_rate off | Adjust `text_prompt` length, or tweak `speech_rate` by ±5 |
| Timing feels wrong | No punctuation / rhythm cues in prompt | Add commas, periods, `—` for pauses; describe pace explicitly |
