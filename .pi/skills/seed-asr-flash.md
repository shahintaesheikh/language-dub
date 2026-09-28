# BytePlus Seed Speech — ASR Audio File, Fast Mode (`recognize/flash`)

> Agent reference. Source: https://docs.byteplus.com/en/docs/byteplusvoice/asraudiofile-flash (page last updated July 1, 2026).
> Legend: **[doc]** = stated on the official page. **[inferred]** = my inference from the doc/sample code, verify before relying on it.

## 1. Mental model

Single-shot, synchronous transcription: **one POST in, one JSON transcript out**. No submit/poll cycle (that is the *Standard Mode* API: `asraudiofilesubmittask` + `asraudiofilequeryresult`). Use Flash for files **≤ 2 h and ≤ 100 MB**; use Standard Mode beyond that. [doc]

Backed by the Seed ASR large speech model (`model_name: "bigmodel"`, the only allowed value). Supports LLM-style context injection (hotwords, dialogue history, an image).

## 2. Endpoint

```
POST https://voice.ap-southeast-1.bytepluses.com/api/v3/auc/bigmodel/recognize/flash
Content-Type: application/json
```

## 3. Headers

| Header | Req | Value |
|---|---|---|
| `X-Api-Key` | yes | API key generated in the BytePlus console |
| `X-Api-Resource-Id` | yes | Fixed: `volc.seedasr.auc_turbo` |
| `X-Api-Request-Id` | yes | Task/request ID. Use a fresh random UUID per request |
| `X-Api-Sequence` | no | Fixed: `-1` (send it; all official samples do) |
| `Content-Type` | yes [inferred] | `application/json` |

## 4. Request body

```jsonc
{
  "audio":   { /* what to transcribe */ },
  "request": { /* how to transcribe it */ }
}
```

### 4.1 `audio`

| Field | Type | Notes |
|---|---|---|
| `url` | string | Publicly reachable HTTP(S) URL. Max 2 h, max 100 MB. Doc labels it "required" |
| `data` | string | Base64 audio bytes. Doc: "Either this or `url` must be provided" |
| `format` | string | Container: `raw` / `wav` / `mp3` / `ogg` |
| `codec` | string | `raw` (PCM, default) / `opus` |
| `rate` | int | Sample rate Hz, default `16000` |
| `bits` | int | Bit depth, default `16` |
| `channel` | int | `1` mono (default) / `2` stereo |
| `language` | string | See §6. Empty = default multi-dialect Chinese + English recognition |

Note: the doc marks `url` "required" but also says `data` is an alternative. [inferred] Send exactly one of them. For `raw` PCM input, `rate`/`bits`/`channel` must match the real audio since there is no header to read them from. For wav/mp3/ogg, still set `format`.

### 4.2 `request`

| Field | Type | Default | Notes |
|---|---|---|---|
| `model_name` | string | — | Required. Only `"bigmodel"` |
| `enable_itn` | bool | `true` | Inverse text normalization: spoken form to written form ("one hundred" to "100") |
| `enable_punc` | bool | `false` | Punctuation. **Off by default; you almost always want `true`** |
| `enable_ddc` | bool | `false` | Semantic smoothing: removes/rewrites pauses, fillers, repetitions |
| `enable_speaker_info` | bool | `false` | Diarization. Best with ≤ 10 speakers; degrades with big volume/distance variation |
| `enable_channel_split` | bool | `false` | Dual-channel recognition. Utterances tagged `channel_id` `"1"` = left, `"2"` = right |
| `show_utterances` | bool | — | Return utterance- and word-level segmentation with timestamps. Needed for timestamps and speaker labels |
| `vad_segment` | bool | `false` | Use VAD for sentence segmentation. Usually needed together with dual-channel |
| `end_window_size` | int | — | Min silence (ms) that ends a sentence. Range 300–5000. Recommended 800–1000; ≤ 500 for latency-sensitive use. **Setting it disables semantic segmentation** (silence drives segmentation instead) |
| `enable_auto_lang` | bool | `false` | Auto-detect language and route to the matching cluster. If `language` is also set, **the auto-detected result wins** |
| `output_zh_variant` | string | — | Simplified to Traditional conversion: `traditional` (Mainland), `tw` (Taiwan), `hk` (Hong Kong) |
| `sensitive_words_filter` | string | — | Output filtering, container for the three below |
| `system_reserved_filter` | bool | — | Apply the built-in restricted-vocabulary list; matches are replaced with `*` |
| `filter_with_empty` | string | — | Custom words to delete from output |
| `filter_with_signed` | string | — | Custom words to replace with `*` |
| `corpus` | dict | — | Corpus/intervention config; holds `context` |
| `context` | string | — | **JSON-encoded string** (not an object) with hotwords / dialogue context / image. See §5 |

The doc is ambiguous about the nesting of `sensitive_words_filter` / `system_reserved_filter` / `filter_with_*` and `context` (rendered as an indented tree under `corpus`). [inferred] `context` most likely lives at `request.corpus.context`, and the filter fields probably live inside `request.sensitive_words_filter` (which the doc types as string, likely a JSON string in the same style as `context`). **Test both placements against the live API** before shipping; do not assume.

## 5. `context` (hotwords, dialogue, visual)

`context` must be a **string containing JSON** (double-encode it). [doc]

Hotwords (up to **5,000 words** per request):

```json
"context": "{\"hotwords\":[{\"word\":\"one\"},{\"word\":\"two\"}]}"
```

Dialogue context (up to **800 tokens across 20 turns**; oldest turns are truncated first; `context_data` is ordered **newest to oldest**). Can carry dialogue history, bot info, personalization info, business-scenario description:

```json
{
  "context_type": "dialog_ctx",
  "context_data": [
    {"text": "text1"},
    {"image_url": "image_url"},
    {"text": "text2"}
  ]
}
```

Visual context (Seed ASR 2.0): 1 image per request, ≤ 500 KB, JPEG/JPG/PNG, passed via `image_url` in `context_data`.

Hotword hygiene [inferred]: keep hotwords to real domain vocabulary (product names, people, jargon). Padding with thousands of common words dilutes bias.

## 6. Languages (`audio.language`)

Empty = Mandarin, English, Cantonese, Shanghainese, Minnan, Sichuan, Shaanxi dialects.
Otherwise set one of:

`en-US` `zh-CN` `yue-CN` `ja-JP` `id-ID` `es-MX` `pt-BR` `de-DE` `fr-FR` `ko-KR` `fil-PH` `ms-MY` `th-TH` `ar-SA` `it-IT` `bn-BD` `el-GR` `nl-NL` `ru-RU` `tr-TR` `vi-VN` `pl-PL` `ro-RO` `uk-UA` `az-AZ` `bg-BG` `cs-CZ` `da-DK` `fi-FI` `hi-IN` `hu-HU` `kk-KZ` `km-KH` `my-MM` `no-NO` `pa-PK` `sv-SE` `sw-KE` `ur-PK`

CJK output may contain Unicode escapes; make sure your JSON parser decodes them (in Python, write files with `ensure_ascii=False`).

## 7. Response

HTTP body (JSON):

| Path | Type | Meaning |
|---|---|---|
| `audio_info.duration` | int | Audio length, ms |
| `result.text` | string | Full transcript |
| `result.additions.duration` | string | Duration, ms (string typed) |
| `result.utterances[]` | list | Only when `show_utterances: true` |
| `…utterances[].text` | string | Sentence text |
| `…utterances[].start_time` / `end_time` | int | ms offsets |
| `…utterances[].additions.channel_id` | string | Channel index |
| `…utterances[].additions.speaker` | string | Diarization label (with `enable_speaker_info`) |
| `…utterances[].words[]` | list | Word tokens |
| `…words[].text` / `start_time` / `end_time` | | Token + ms offsets |
| `…words[].confidence` | float | Confidence score |

Quirks observed in the official example [doc example]:
- Whitespace appears as its own word token (`" "`) with `start_time`/`end_time` of `-1`. Filter tokens where `start_time < 0` when building word-level timings.
- `confidence` is `0` for every word in the sample. Do not build logic on it without checking real output.
- `duration` is an int in `audio_info` but a string in `result.additions`.

### Status is in the response HEADERS

The official Python sample reads status from **response headers**, not the body:

| Header | Meaning |
|---|---|
| `X-Api-Status-Code` | `20000000` = success (finished). `20000001` / `20000002` are treated as in-progress/queued in the sample (carried over from Standard Mode; not expected for Flash). Anything else = failure |
| `X-Api-Message` | Human-readable status message |
| `X-Tt-Logid` | Server log ID. **Log it on every request** and include it in support tickets |

The page does **not** publish a full error-code table. [doc gap] Treat non-`20000000` as failure and surface `X-Api-Message` + `X-Tt-Logid`.

## 8. Working examples

### cURL

```bash
curl -X POST "https://voice.ap-southeast-1.bytepluses.com/api/v3/auc/bigmodel/recognize/flash" \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: <your_api_key>" \
  -H "X-Api-Resource-Id: volc.seedasr.auc_turbo" \
  -H "X-Api-Request-Id: $(uuidgen)" \
  -H "X-Api-Sequence: -1" \
  -d '{
    "audio": { "url": "<audio_file_url>" },
    "request": {
      "model_name": "bigmodel",
      "enable_itn": true,
      "enable_punc": true,
      "enable_ddc": true,
      "enable_speaker_info": false,
      "show_utterances": true
    }
  }'
```

### Python (adapted from the official sample, with local-file base64 support)

```python
import base64, json, os, uuid
import requests

URL = "https://voice.ap-southeast-1.bytepluses.com/api/v3/auc/bigmodel/recognize/flash"

def transcribe(audio_url: str | None = None, file_path: str | None = None,
               language: str | None = None, **opts) -> dict:
    assert (audio_url is None) != (file_path is None), "pass exactly one of audio_url / file_path"

    audio: dict = {}
    if audio_url:
        audio["url"] = audio_url
    else:
        with open(file_path, "rb") as f:
            audio["data"] = base64.b64encode(f.read()).decode()
        audio["format"] = os.path.splitext(file_path)[1].lstrip(".").lower()  # wav / mp3 / ogg
    if language:
        audio["language"] = language

    body = {
        "audio": audio,
        "request": {
            "model_name": "bigmodel",
            "enable_itn": True,
            "enable_punc": True,
            "enable_ddc": False,
            "show_utterances": True,
            **opts,   # e.g. enable_speaker_info=True
        },
    }
    headers = {
        "X-Api-Key": os.environ["BYTEPLUS_ASR_API_KEY"],
        "X-Api-Resource-Id": "volc.seedasr.auc_turbo",
        "X-Api-Request-Id": str(uuid.uuid4()),
        "X-Api-Sequence": "-1",
    }
    r = requests.post(URL, json=body, headers=headers, timeout=300)

    code = r.headers.get("X-Api-Status-Code")
    logid = r.headers.get("X-Tt-Logid")
    if code != "20000000":
        raise RuntimeError(f"ASR failed code={code} msg={r.headers.get('X-Api-Message')} logid={logid} http={r.status_code}")
    return r.json()

if __name__ == "__main__":
    out = transcribe(audio_url="<audio_file_url>")
    print(out["result"]["text"])
    with open("result.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
```

Go and Java samples on the official page follow the identical header/body shape (Java 15+ text blocks + `java.net.http`; Go stdlib `net/http` with a hand-rolled UUID v4). Note they only print HTTP status and body; **they don't check `X-Api-Status-Code`**, so add that check yourself.

## 9. Best practices

Documented:
1. Use Flash for ≤ 2 h / ≤ 100 MB; otherwise Standard Mode.
2. Turn on `enable_punc` (default off) and keep `enable_itn` on for readable output.
3. `enable_ddc` cleans disfluencies. Great for reading, but it **rewrites** speech, so keep it off for verbatim/legal transcripts.
4. `end_window_size`: 800–1000 ms normal, ≤ 500 ms for latency-sensitive. Setting it turns off semantic segmentation.
5. Diarization: ≤ 10 speakers, consistent acoustics.
6. Dual-channel (call recordings): `channel: 2` + `enable_channel_split` + `vad_segment: true`.
7. Feed `context` (hotwords, dialogue history, business scenario) for domain terms and accents. It must be a JSON **string**.
8. Use a fresh UUID for `X-Api-Request-Id`.
9. Decode Unicode properly for CJK output.

Inferred (verify):
- Prefer `audio.url` for large files (avoids base64 +33% bloat and request-size limits). Use `data` for small local clips.
- Downmix/resample to 16 kHz mono PCM or a standard wav/mp3 before upload if you control the source; it matches the defaults.
- Pin `language` when you know it. It is more predictable than the empty default (which biases to Mandarin/English/dialects). Note `enable_auto_lang: true` overrides `language`.
- Set a generous client timeout (long files take real time on a synchronous call) and retry only on transport errors/5xx with a **new** request ID.
- Never log the API key. Load from env/secret store.
- Timestamps/speakers need `show_utterances: true`; without it you get only `result.text`.

## 10. Gotchas checklist

- `X-Api-Resource-Id` is the literal `volc.seedasr.auc_turbo` (not the Standard-mode resource ID).
- Success = header `X-Api-Status-Code == 20000000`. HTTP 200 alone is not proof.
- `context` is a string, not an object.
- `language` + `enable_auto_lang=true`: auto-detect wins.
- `end_window_size` silently disables semantic sentence splitting.
- Word arrays include `-1`-timestamp whitespace tokens.
- Region host is `ap-southeast-1` (`voice.ap-southeast-1.bytepluses.com`); the doc lists no other region.
- Documentation gaps: no error-code table, no rate/QPS limits, no stated request-size cap for base64 `data`, ambiguous nesting for `context` and the filter fields.
