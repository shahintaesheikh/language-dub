"""ASR — speech-to-text via seed-2-0-lite (ModelArk Chat Completions)."""

import base64
import json
import time
import urllib.request as _req

from . import config


def transcribe(audio_wav_path: str, source_lang: str = "English") -> dict:
    """
    Transcribe a WAV file using seed-2-0-lite via ModelArk Chat Completions.

    Returns:
        {"text": "...", "duration_ms": 0, "utterances": [], "logid": ""}
    """
    with open(audio_wav_path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode()

    payload = {
        "model": config.SEED20_LITE_MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "input_audio", "input_audio": {"data": audio_b64, "format": "wav"}},
            {"type": "text", "text": "Transcribe this audio verbatim. Return only the exact words spoken, no commentary."}
        ]}],
        "max_tokens": 4000,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.ARK_API_KEY}",
    }

    req = _req.Request(config.MODELARK_CHAT_URL, data=json.dumps(payload).encode(),
                       headers=headers, method="POST")

    try:
        with _req.urlopen(req, timeout=600) as resp:
            result = json.loads(resp.read())
    except _req.HTTPError as e:
        body = e.read().decode()[:500]
        print(f"[dub] ASR HTTP {e.code}: {body}")
        raise RuntimeError(f"ASR API HTTP error {e.code}")
    except Exception as e:
        print(f"[dub] ASR network error: {e}")
        raise

    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not content:
        print("[dub] ASR returned empty transcript")
        return {"text": "", "utterances": [], "duration_ms": 0, "logid": ""}

    print(f"[dub]   ASR ({len(content)} chars)")
    return {"text": content, "utterances": [], "duration_ms": 0, "logid": ""}