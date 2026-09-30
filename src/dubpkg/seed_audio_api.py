"""Seed Audio 1.0 — TTS/TA2A generation via BytePlus Voice API."""

import base64
import json
import time
import urllib.request as _req

from . import config


def generate(audio_data_b64: str, prompt: str,
             speech_rate: int = 0,
             sample_rate: int = 24000,
             audio_format: str = "wav") -> dict:
    """
    Call Seed Audio 1.0 (TA2A mode with reference audio).

    Returns:
        {"audio_b64": "...", "duration": float, "original_duration": float, "url": ""}
    """
    import uuid

    payload = {
        "model": config.SEED_AUDIO_MODEL,
        "text_prompt": prompt,
        "references": [{"audio_data": audio_data_b64}],
        "audio_config": {
            "format": audio_format,
            "sample_rate": sample_rate,
            "speech_rate": max(-50, min(100, speech_rate)),
        },
        "watermark": {"aigc_watermark": False, "aigc_metadata": {"enable": False}},
    }

    req = _req.Request(
        config.SEED_AUDIO_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Api-Key": config.SPEECH_API_KEY,
            "X-Api-Request-Id": str(uuid.uuid4()),
        },
        method="POST",
    )

    try:
        with _req.urlopen(req, timeout=130) as resp:
            result = json.loads(resp.read())
    except Exception as e:
        print(f"[dub] Seed Audio network error: {e}")
        raise

    if result.get("code") is not None and result.get("code") != 200:
        raise RuntimeError(
            f"Seed Audio API error (code {result.get('code')}): "
            f"{result.get('message', 'unknown')}"
        )

    return {"audio_b64": result["audio"],
            "duration": result.get("duration", 0),
            "original_duration": result.get("original_duration", 0),
            "url": result.get("url", "")}


def generate_textonly(prompt: str, speech_rate: int = 0,
                      sample_rate: int = 24000, audio_format: str = "wav") -> dict:
    """Text-only T2A generation (no reference audio)."""
    import uuid

    payload = {
        "model": config.SEED_AUDIO_MODEL,
        "text_prompt": prompt,
        "audio_config": {
            "format": audio_format,
            "sample_rate": sample_rate,
            "speech_rate": max(-50, min(100, speech_rate)),
        },
        "watermark": {"aigc_watermark": False, "aigc_metadata": {"enable": False}},
    }

    req = _req.Request(
        config.SEED_AUDIO_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Api-Key": config.SPEECH_API_KEY,
            "X-Api-Request-Id": str(uuid.uuid4()),
        },
        method="POST",
    )

    try:
        with _req.urlopen(req, timeout=130) as resp:
            result = json.loads(resp.read())
    except Exception as e:
        print(f"[dub] Seed Audio network error: {e}")
        raise

    if result.get("code") is not None and result.get("code") != 200:
        raise RuntimeError(
            f"Seed Audio API error (code {result.get('code')}): "
            f"{result.get('message', 'unknown')}"
        )

    return {"audio_b64": result["audio"],
            "duration": result.get("duration", 0),
            "original_duration": result.get("original_duration", 0),
            "url": result.get("url", "")}


def duration_matching_loop(audio_data_b64: str, prompt: str,
                           target_duration: float, sample_rate: int,
                           initial_speech_rate: int = 0,
                           max_iterations: int = None) -> dict:
    """
    Generate dubbed audio, compare to target_duration, adjust speech_rate, repeat.
    Returns the best result dict.
    """
    if max_iterations is None:
        max_iterations = config.MAX_SPEECH_ADJUST_ITERATIONS

    trial = 0
    speech_rate = initial_speech_rate
    best_result = None
    best_error = float("inf")

    while trial < max_iterations:
        print(f"[dub]   Trial {trial + 1}: speech_rate={speech_rate}")
        result = generate(audio_data_b64=audio_data_b64, prompt=prompt,
                          speech_rate=speech_rate, sample_rate=sample_rate)
        dubbed_dur = result.get("duration", 0)
        if dubbed_dur <= 0:
            return result

        error = abs(dubbed_dur - target_duration) / max(target_duration, 0.01)
        print(f"[dub]   → duration={dubbed_dur:.2f}s, error={error:.1%}, "
              f"target={target_duration:.2f}s")

        if error < best_error:
            best_error = error
            best_result = result

        if error <= config.DURATION_TOLERANCE:
            print(f"[dub]   ✓ Within tolerance")
            return result

        # speech_rate → speed: -50=0.5x, 0=1.0x, +100=2.0x
        current_speed = 1.0 + speech_rate / 100.0
        baseline_dur = dubbed_dur * current_speed
        target_speed = baseline_dur / target_duration
        new_speech_rate = int(round((target_speed - 1.0) * 100))
        speech_rate = max(-30, min(30, new_speech_rate))
        trial += 1

    print(f"[dub]   ⚠ Best error after {trial} tries: {best_error:.1%}")
    return best_result or result