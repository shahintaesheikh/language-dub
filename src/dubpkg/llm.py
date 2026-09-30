"""LLM — Seed 2.1 prompt generation via ModelArk Chat Completions."""

import json
import re
import urllib.request as _req

from . import config


def generate_prompt(transcript: str, source_duration: float,
                    source_lang: str, target_lang: str,
                    chunk_index: int = None, total_chunks: int = None) -> dict:
    """
    Call dola-seed-2-1-turbo to produce a Seed Audio dubbing prompt.

    Returns:
        {"prompt": "...", "translation": "...", "speech_rate": 0,
         "emotion": "...", "pace": "...", "prompt_english": "...", "reasoning": "..."}
    """
    chunk_hint = ""
    if chunk_index is not None and total_chunks is not None:
        chunk_hint = (
            f"This is chunk {chunk_index + 1} of {total_chunks} of the full audio. "
            f"Focus on making this segment flow naturally as part of a longer piece. "
            f"Keep the voice character consistent with the overall dubbing.\n"
        )

    instructions = (
        "You are a dubbing prompt engineer for Seed Audio 1.0. "
        "Translate from {source_lang} to {target_lang}. "
        f"Source duration: {source_duration:.1f}s.\n"
        + chunk_hint +
        "\nRules:\n"
        "- Translate meaning-first, keep syllable count similar to original.\n"
        "- Write the ENTIRE Seed Audio prompt in {target_lang} (never English).\n"
        "- Include @Audio1 as the voice reference tag.\n"
        "- Estimate speech_rate (0=1.0x, -10=~0.9x, +10=~1.1x) to match the source duration.\n"
        "- Return ONLY valid JSON (no markdown, no commentary):\n"
        '{{"prompt":"...","translation":"...","speech_rate":0,'
        '"emotion":"...","pace":"...",'
        '"prompt_english":"..."}}'
    ).format(source_lang=source_lang, target_lang=target_lang)

    user_msg = (
        f"Source language: {source_lang}\n"
        f"Target language: {target_lang}\n"
        f"Source duration: {source_duration:.2f}s\n"
        f"Transcript:\n{transcript}\n\n"
        "Generate the Seed Audio dubbing prompt in the target language as a JSON object."
    )

    payload = {
        "model": config.SEED21_MODEL,
        "messages": [{"role": "user", "content": instructions + "\n\n" + user_msg}],
        "temperature": 0.3,
        "max_tokens": 1024,
        "reasoning_effort": "minimal",
    }

    req = _req.Request(
        config.MODELARK_CHAT_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {config.ARK_API_KEY}"},
        method="POST",
    )

    try:
        with _req.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read())
    except _req.HTTPError as e:
        body = e.read().decode()[:500]
        print(f"[dub] LLM HTTP {e.code}: {body}")
        raise RuntimeError(f"LLM API HTTP error {e.code}")
    except Exception as e:
        print(f"[dub] LLM network error: {e}")
        raise

    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")

    # Try to parse JSON from the response
    json_match = re.search(r"\{[\s\S]*\}", content)
    if json_match:
        try:
            parsed = json.loads(json_match.group(0))
            parsed.setdefault("prompt", "")
            parsed.setdefault("speech_rate", 0)
            parsed.setdefault("translation", "")
            parsed.setdefault("emotion", "")
            parsed.setdefault("pace", "")
            parsed.setdefault("prompt_english", "")
            parsed.setdefault("reasoning", content)
            return parsed
        except json.JSONDecodeError:
            pass

    return {"prompt": content.strip(), "speech_rate": 0, "translation": "",
            "emotion": "", "pace": "", "prompt_english": "", "reasoning": content}