#!/usr/bin/env python3
"""
Video Dubbing Pipeline — Seed 2.1 LLM + Seed Audio 1.0 + ffmpeg
===============================================================
Accepts a video + target language, uses Seed 2.1 LLM to generate a Seed Audio 1.0
prompt, calls the Seed Audio API to produce dubbed audio, and muxes the new audio
into the original video with ffmpeg.

Supports **long-form content**: videos longer than 60s are automatically split into
chunks, each chunk is dubbed independently, then stitched back together.

Usage:
  python3 dub.py --video input.mp4 --target-lang "French" [options]

Requires:
  - ARK_API_KEY and SPEECH_API_KEY in /Users/bytedance/dhar/.env
  - arkcli (for Seed 2.1 LLM via raw create_chat_completion)
  - ffmpeg/ffprobe on PATH
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Config ──────────────────────────────────────────────────────────
ENV_FILE = os.path.expanduser("/Users/bytedance/dhar/.env")
SEED21_MODEL = "dola-seed-2-1-turbo-260628"
SEED_AUDIO_MODEL = "seed-audio-1.0"
SEED_AUDIO_URL = "https://voice.ap-southeast-1.bytepluses.com/api/v3/tts/create"
MAX_SPEECH_ADJUST_ITERATIONS = 3
DURATION_TOLERANCE = 0.15          # ±15% tolerance for duration matching
CHUNK_THRESHOLD = 90               # seconds — above this we chunk
CHUNK_MAX_DURATION = 60            # seconds per chunk
REF_AUDIO_MAX_SEC = 30             # max reference audio duration for Seed Audio

LOG_FILE = os.path.expanduser("/Users/bytedance/dhar/work/dub_log.json")

ARK_API_KEY = None
SPEECH_API_KEY = None


def load_env():
    """Read API keys from .env file."""
    global ARK_API_KEY, SPEECH_API_KEY
    if not os.path.exists(ENV_FILE):
        print(f"[dub] Error: {ENV_FILE} not found. Create it with ARK_API_KEY and SPEECH_API_KEY.")
        sys.exit(1)
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line.startswith("ARK_API_KEY="):
                ARK_API_KEY = line.split("=", 1)[1].strip('"').strip("'")
            elif line.startswith("SPEECH_API_KEY="):
                SPEECH_API_KEY = line.split("=", 1)[1].strip('"').strip("'")
    if not ARK_API_KEY or not SPEECH_API_KEY:
        print(f"[dub] Error: ARK_API_KEY and SPEECH_API_KEY must be set in {ENV_FILE}")
        sys.exit(1)


# ── Logging ───────────────────────────────────────────────────────

def append_log(entry: dict):
    """Append a Seed Audio generation entry to the shared JSON log."""
    import json as _json, os as _os
    entries = []
    if _os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r") as f:
                entries = _json.load(f)
                if not isinstance(entries, list):
                    entries = [entries]
        except Exception:
            entries = []
    entries.append(entry)
    with open(LOG_FILE, "w") as f:
        _json.dump(entries, f, indent=2, ensure_ascii=False)


# ── FFmpeg helpers ──────────────────────────────────────────────────

def ffprobe_duration(path: str) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "default=nw=1:nk=1", path],
                       capture_output=True, text=True, timeout=30)
    return float(r.stdout.strip())


def ffprobe_audio_info(path: str) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0",
                        "-show_entries", "stream=sample_rate,channels,codec_name",
                        "-of", "json", path],
                       capture_output=True, text=True, timeout=30)
    streams = json.loads(r.stdout).get("streams", [])
    if not streams:
        return {}
    s = streams[0]
    return {"sample_rate": int(s.get("sample_rate", 24000)),
            "channels": int(s.get("channels", 1)),
            "codec": s.get("codec_name", "aac")}


def extract_audio(source_video: str, out_wav: str):
    """Extract first audio stream to 16kHz mono WAV."""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-i", source_video,
                    "-vn", "-acodec", "pcm_s16le",
                    "-ar", "16000", "-ac", "1", out_wav],
                   check=True, timeout=300)


def extract_audio_segment(source_video: str, out_wav: str,
                          start_sec: float, duration_sec: float):
    """Extract a segment of the first audio stream."""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-i", source_video,
                    "-vn", "-acodec", "pcm_s16le",
                    "-ar", "16000", "-ac", "1",
                    "-ss", str(start_sec), "-t", str(duration_sec),
                    out_wav],
                   check=True, timeout=300)


def mux_audio(video_path: str, new_audio_path: str, output_path: str):
    """Replace original audio with new audio while keeping the video stream."""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-i", video_path, "-i", new_audio_path,
                    "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k",
                    "-shortest", output_path],
                   check=True, timeout=300)


def concat_audios(input_wavs: list, output_wav: str):
    """Concatenate multiple WAV files using ffmpeg concat demuxer."""
    if len(input_wavs) == 1:
        subprocess.run(["cp", input_wavs[0], output_wav], check=True)
        return
    # Write concat list file
    concat_file = os.path.join(os.path.dirname(output_wav) or ".", "_concat_list.txt")
    with open(concat_file, "w") as f:
        for w in input_wavs:
            f.write(f"file '{os.path.abspath(w)}'\n")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-f", "concat", "-safe", "0",
                    "-i", concat_file,
                    "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                    output_wav],
                   check=True, timeout=300)
    os.remove(concat_file)


# ── LLM step ────────────────────────────────────────────────────────

def llm_generate_prompt(transcript: str, source_duration: float,
                         source_lang: str, target_lang: str,
                         chunk_index: int = None, total_chunks: int = None) -> dict:
    """
    Call Seed 2.1 (dola-seed-2-1-turbo) via raw chat_completion.
    The LLM analyzes the transcript + timing and produces a Seed Audio
    prompt IN THE TARGET LANGUAGE.

    Returns: {"prompt": "...", "speech_rate": 0, "translation": "...", "reasoning": "..."}
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
        "model": SEED21_MODEL,
        "messages": [
            {"role": "user", "content": instructions + "\n\n" + user_msg}
        ],
        "temperature": 0.3,
        "max_tokens": 1024,
        "reasoning_effort": "minimal"
    }

    import urllib.request

    MODELARK_URL = "https://ark.ap-southeast.bytepluses.com/api/v3/chat/completions"

    req = urllib.request.Request(
        MODELARK_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {ARK_API_KEY}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500]
        print(f"[dub] LLM HTTP {e.code}: {body}")
        raise RuntimeError(f"LLM API HTTP error {e.code}")
    except Exception as e:
        print(f"[dub] LLM network error: {e}")
        raise

    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")

    # Try to parse JSON from the response (model may wrap in markdown)
    json_match = re.search(r"\{[\s\S]*\}", content)
    if json_match:
        try:
            parsed = json.loads(json_match.group(0))
            parsed.setdefault("prompt", "")
            parsed.setdefault("speech_rate", 0)
            parsed.setdefault("translation", "")
            parsed.setdefault("reasoning", content)
            parsed.setdefault("prompt_english", "")
            return parsed
        except json.JSONDecodeError:
            pass

    # Fallback: treat raw content as the prompt
    return {"prompt": content.strip(), "speech_rate": 0, "translation": "", "reasoning": content, "prompt_english": ""}


# ── Seed Audio API step ─────────────────────────────────────────────

def seed_audio_generate(audio_data_b64: str, prompt: str,
                         speech_rate: int = 0,
                         sample_rate: int = 24000,
                         audio_format: str = "wav") -> dict:
    """Call Seed Audio 1.0 TTS endpoint (TA2A mode with reference audio)."""
    payload = {
        "model": SEED_AUDIO_MODEL,
        "text_prompt": prompt,
        "references": [{"audio_data": audio_data_b64}],
        "audio_config": {
            "format": audio_format,
            "sample_rate": sample_rate,
            "speech_rate": max(-50, min(100, speech_rate)),
        },
        "watermark": {"aigc_watermark": False, "aigc_metadata": {"enable": False}}
    }

    import urllib.request
    req = urllib.request.Request(
        SEED_AUDIO_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "X-Api-Key": SPEECH_API_KEY,
                 "X-Api-Request-Id": str(uuid.uuid4())},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=130) as resp:
            result = json.loads(resp.read())
    except Exception as e:
        print(f"[dub] Seed Audio network error: {e}")
        raise

    if result.get("code") is not None and result.get("code") != 200:
        raise RuntimeError(
            f"Seed Audio API error (code {result.get('code')}): {result.get('message', 'unknown')}"
        )

    return {"audio_b64": result["audio"], "duration": result.get("duration", 0),
            "original_duration": result.get("original_duration", 0), "url": result.get("url", "")}


# ── Duration matching loop ──────────────────────────────────────────

def duration_matching_loop(audio_data_b64: str, prompt: str,
                           target_duration: float, sample_rate: int,
                           initial_speech_rate: int = 0,
                           max_iterations: int = MAX_SPEECH_ADJUST_ITERATIONS) -> dict:
    """Generate audio, compare to target_duration, adjust speech_rate, repeat."""
    trial = 0
    speech_rate = initial_speech_rate
    best_result = None
    best_error = float("inf")

    while trial < max_iterations:
        print(f"[dub]   Trial {trial + 1}: speech_rate={speech_rate}")
        result = seed_audio_generate(audio_data_b64=audio_data_b64, prompt=prompt,
                                      speech_rate=speech_rate, sample_rate=sample_rate)
        dubbed_dur = result.get("duration", 0)
        if dubbed_dur <= 0:
            return result
        error = abs(dubbed_dur - target_duration) / max(target_duration, 0.01)
        print(f"[dub]   → duration={dubbed_dur:.2f}s, error={error:.1%}, target={target_duration:.2f}s")
        if error < best_error:
            best_error = error
            best_result = result
        if error <= DURATION_TOLERANCE:
            print(f"[dub]   ✓ Within tolerance")
            return result

        # speech_rate mapping: -50=0.5x, 0=1.0x, +100=2.0x
        current_speed = 1.0 + speech_rate / 100.0
        baseline_dur = dubbed_dur * current_speed
        target_speed = baseline_dur / target_duration
        new_speech_rate = int(round((target_speed - 1.0) * 100))
        speech_rate = max(-30, min(30, new_speech_rate))
        trial += 1

    print(f"[dub]   ⚠ Best error after {trial} tries: {best_error:.1%}")
    return best_result or result


# ── Chunking / stitching ────────────────────────────────────────────

def _dub_chunk_worker(args):
    """Worker for parallel chunk dubbing. Args is a tuple of all parameters."""
    (video_path, source_lang, target_lang, chunk_transcript,
     start_sec, end_sec, seg_dur, i, num_chunks, chunk_b64,
     no_duration_loop, workdir) = args

    import base64 as _b64

    print(f"[dub]   Chunk {i + 1}: worker starting ({start_sec:.1f}s–{end_sec:.1f}s)")

    # LLM prompt generation for this chunk
    llm_result = llm_generate_prompt(
        transcript=chunk_transcript if chunk_transcript else
        f"[Chunk {i + 1} of {num_chunks}, duration {seg_dur:.1f}s, no transcript]",
        source_duration=seg_dur,
        source_lang=source_lang,
        target_lang=target_lang,
        chunk_index=i,
        total_chunks=num_chunks,
    )
    prompt = llm_result.get("prompt", "")
    est_speech_rate = llm_result.get("speech_rate", 0)

    if not prompt:
        prompt = f"@Audio1 Speak naturally in {target_lang}: {chunk_transcript or '[content omitted]'}"

    # Generate dubbed audio
    if no_duration_loop:
        result = seed_audio_generate(audio_data_b64=chunk_b64, prompt=prompt,
                                      speech_rate=est_speech_rate)
    else:
        result = duration_matching_loop(audio_data_b64=chunk_b64, prompt=prompt,
                                         target_duration=seg_dur, sample_rate=16000,
                                         initial_speech_rate=est_speech_rate)

    dubbed_dur = result.get("duration", 0)
    dur_err = abs(dubbed_dur - seg_dur) / max(seg_dur, 0.01) * 100
    append_log({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "video_source": os.path.basename(video_path),
        "target_language": target_lang,
        "source_language": source_lang,
        "chunk": i + 1,
        "chunk_total": num_chunks,
        "chunk_range_s": [round(start_sec, 1), round(end_sec, 1)],
        "original_english_transcript": chunk_transcript or "",
        "seed_audio_prompt_french": prompt,
        "seed_audio_prompt_english": llm_result.get("prompt_english", ""),
        "duration_mismatch_pct": round(dur_err, 1),
        "source_duration_s": round(seg_dur, 2),
        "generated_duration_s": round(dubbed_dur, 2),
        "model_params": {
            "model": SEED_AUDIO_MODEL,
            "speech_rate": est_speech_rate,
            "sample_rate": 16000,
            "format": "wav",
        },
        "seed21_emotion": llm_result.get("emotion", ""),
        "seed21_pace": llm_result.get("pace", ""),
        "seed21_speech_rate_est": est_speech_rate,
    })

    chunk_wav = os.path.join(workdir, f"chunk{i}_dubbed.wav")
    with open(chunk_wav, "wb") as f:
        f.write(_b64.b64decode(result["audio_b64"]))

    print(f"[dub]   Chunk {i + 1}: done, duration={result.get('duration', 0):.1f}s")

    return (i, chunk_wav)


def chunk_and_dub_audio(video_path: str, source_lang: str, target_lang: str,
                         full_transcript: str, workdir: str,
                         no_duration_loop: bool, utterances: list = None,
                         max_workers: int = 4) -> str:
    """
    Split a long video into chunks (max CHUNK_MAX_DURATION s each), dub each
    chunk independently, then stitch all chunks into one WAV.

    Returns: path to stitched output WAV.
    """
    source_duration = ffprobe_duration(video_path)
    num_chunks = max(1, int(source_duration / CHUNK_MAX_DURATION) +
                     (1 if source_duration % CHUNK_MAX_DURATION > 0 else 0))
    chunk_dur = source_duration / num_chunks  # equal-length chunks

    print(f"[dub] Long audio ({source_duration:.0f}s): splitting into {num_chunks} chunks "
          f"of ~{chunk_dur:.1f}s each")

    # Split full transcript into chunks
    chunk_transcripts = []
    if utterances and len(utterances) > 1:
        # Use utterance timestamps for precise per-chunk transcripts
        utt_idx = 0
        for i in range(num_chunks):
            chunk_start = i * chunk_dur * 1000  # ms
            chunk_end = (i + 1) * chunk_dur * 1000
            seg_utts = []
            while utt_idx < len(utterances) and utterances[utt_idx].get("end_time", 0) <= chunk_start:
                utt_idx += 1
            while utt_idx < len(utterances) and utterances[utt_idx].get("start_time", 0) < chunk_end:
                seg_utts.append(utterances[utt_idx].get("text", ""))
                utt_idx += 1
            chunk_transcripts.append(" ".join(seg_utts))
    else:
        # Fallback: split by sentence proportion
        transcript_lines = (full_transcript or "").split(". ")
        if not transcript_lines or len(transcript_lines) <= num_chunks:
            chunk_transcripts = [full_transcript] * num_chunks
        else:
            lines_per_chunk = max(1, len(transcript_lines) // num_chunks)
            for i in range(num_chunks):
                start_line = i * lines_per_chunk
                end_line = start_line + lines_per_chunk if i < num_chunks - 1 else len(transcript_lines)
                chunk_transcripts.append(". ".join(transcript_lines[start_line:end_line]))
    # ── Prepare chunk args ──────
    chunk_args = []
    for i in range(num_chunks):
        start_sec = i * chunk_dur
        end_sec = min((i + 1) * chunk_dur, source_duration)
        seg_dur = end_sec - start_sec
        seg_transcript = chunk_transcripts[i] if i < len(chunk_transcripts) else full_transcript

        # Extract reference audio (keep ≤ 30s)
        ref_dur = min(seg_dur, REF_AUDIO_MAX_SEC)
        ref_wav = os.path.join(workdir, f"chunk{i}_ref.wav")
        extract_audio_segment(video_path, ref_wav, start_sec, ref_dur)

        with open(ref_wav, "rb") as f:
            ref_b64 = base64.b64encode(f.read()).decode()

        print(f"[dub]   Chunk {i + 1} ref audio: {os.path.getsize(ref_wav)} bytes, {ref_dur:.1f}s")

        chunk_args.append((
            video_path, source_lang, target_lang,
            seg_transcript, start_sec, end_sec, seg_dur,
            i, num_chunks, ref_b64,
            no_duration_loop, workdir,
        ))

    # ── Dub all chunks in parallel ──
    print(f"[dub] Dub-dubbing {len(chunk_args)} chunks with up to {max_workers} parallel workers...")
    results = [None] * num_chunks
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        fut_to_idx = {pool.submit(_dub_chunk_worker, a): a[7] for a in chunk_args}
        for fut in as_completed(fut_to_idx):
            idx, chunk_wav = fut.result()
            results[idx] = chunk_wav

    # ── Stitch all chunks in order ──
    print(f"\n── Stitching {len(results)} chunks in order ──")
    stitched_wav = os.path.join(workdir, "stitched_audio.wav")
    concat_audios(results, stitched_wav)
    stitched_dur = ffprobe_duration(stitched_wav)
    print(f"[dub]   Stitched audio duration: {stitched_dur:.1f}s (target: {source_duration:.1f}s)")

    return stitched_wav


def asr_transcribe(audio_wav_path: str, source_lang: str = "English") -> dict:
    """
    Transcribe audio using seed-2-0-lite via ModelArk Chat Completions API.
    Returns: {"text": "...", "utterances": [{"start_time": ms, "end_time": ms, "text": "..."}],
             "duration_ms": int}
    """
    MODELARK_URL = "https://ark.ap-southeast.bytepluses.com/api/v3/chat/completions"

    with open(audio_wav_path, "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode()

    payload = {
        "model": "seed-2-0-lite-260428",
        "messages": [{"role": "user", "content": [
            {"type": "input_audio", "input_audio": {"data": audio_b64, "format": "wav"}},
            {"type": "text", "text": "Transcribe this audio verbatim. Return only the exact words spoken, no commentary."}
        ]}],
        "max_tokens": 4000,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {ARK_API_KEY}",
    }

    import urllib.request as _req
    req = _req.Request(MODELARK_URL, data=json.dumps(payload).encode(),
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

    print(f"[dub]   ASR transcript ({len(content)} chars): {content[:100]}...")

    return {
        "text": content,
        "utterances": [],
        "duration_ms": 0,
        "logid": "",
    }


# ── Main pipeline ───────────────────────────────────────────────────

def run_pipeline(video_path: str, target_lang: str, source_lang: str = "English",
                 transcript: str = None, output_path: str = None,
                 no_duration_loop: bool = False):
    """Execute the full dubbing pipeline."""
    print("\n" + "=" * 60)
    print("  Video Dubbing Pipeline")
    print(f"  Input:   {video_path}")
    print(f"  Target:  {target_lang}")
    print("=" * 60 + "\n")

    if not os.path.exists(video_path):
        print(f"[dub] Error: video not found: {video_path}")
        sys.exit(1)

    load_env()
    workdir = tempfile.mkdtemp(prefix="dub_")
    print(f"[dub] Working directory: {workdir}")

    if output_path is None:
        base = os.path.splitext(os.path.basename(video_path))[0]
        output_path = f"{base}_dubbed_{target_lang.lower()}.mp4"
    print(f"[dub] Output: {output_path}")

    # ── Step 0: Analyze video ──
    print("\n── Step 0: Analyzing source video ──")
    source_duration = ffprobe_duration(video_path)
    audio_info = ffprobe_audio_info(video_path)
    print(f"[dub]   Video duration: {source_duration:.2f}s")
    print(f"[dub]   Source audio: {audio_info}")

    # ── Step 1: Extract audio ──
    print("\n── Step 1: Extracting source audio ──")
    src_wav = os.path.join(workdir, "source_audio.wav")
    extract_audio(video_path, src_wav)
    print(f"[dub]   Extracted: {src_wav}")

    # ── Step 1b: ASR or user-supplied transcript ──
    if not transcript:
        print("\n── Step 1b: Automatic Speech Recognition ──")
        print(f"[dub]   Language: {source_lang}")
        asr_result = asr_transcribe(src_wav, source_lang=source_lang)
        transcript = asr_result["text"]
        asr_utterances = asr_result["utterances"]
        logid = asr_result.get("logid", "")
        print(f"[dub]   ASR complete ({len(transcript)} chars). LogID: {logid}")
    else:
        print(f"\n── Step 1b: User-supplied transcript ({len(transcript)} chars) ──")

    # ── LONG-FORM: chunk and dub ──
    if source_duration > CHUNK_THRESHOLD:
        print(f"\n── Long-form mode (>{CHUNK_THRESHOLD}s): chunking audio ──")
        final_audio = chunk_and_dub_audio(
            video_path=video_path,
            source_lang=source_lang,
            target_lang=target_lang,
            full_transcript=transcript,
            utterances=asr_utterances,
            workdir=workdir,
            no_duration_loop=no_duration_loop,
        )
    else:
        # ── SHORT-FORM: single pass ──
        print(f"\n── Short-form mode (≤{CHUNK_THRESHOLD}s): single pass ──")

        with open(src_wav, "rb") as f:
            audio_b64 = base64.b64encode(f.read()).decode()

        print(f"\n── Step 2: LLM prompt generation (Seed 2.1) ──")
        print(f"[dub]   Model: {SEED21_MODEL}")
        llm_input = transcript if transcript else transcript_placeholder
        llm_result = llm_generate_prompt(
            transcript=llm_input,
            source_duration=source_duration,
            source_lang=source_lang,
            target_lang=target_lang,
        )
        prompt = llm_result.get("prompt", "")
        est_speech_rate = llm_result.get("speech_rate", 0)
        print(f"[dub]   Emotion: {llm_result.get('emotion', 'N/A')}")
        print(f"[dub]   Pace: {llm_result.get('pace', 'N/A')}")
        print(f"[dub]   Estimated speech_rate: {est_speech_rate}")
        print(f"[dub]   Translation: {llm_result.get('translation', '')[:200]}")
        print(f"[dub]   Prompt: {prompt[:200]}...")

        if not prompt:
            print("[dub] Error: LLM returned empty prompt")
            sys.exit(1)

        print(f"\n── Step 3: Seed Audio generation ──")
        print(f"[dub]   Model: {SEED_AUDIO_MODEL}")
        print(f"[dub]   Reference audio: {len(audio_b64)} bytes base64")
        print(f"[dub]   Target duration: {source_duration:.2f}s")

        final_audio = os.path.join(workdir, "dubbed_audio.wav")

        if no_duration_loop:
            result = seed_audio_generate(audio_data_b64=audio_b64, prompt=prompt,
                                          speech_rate=est_speech_rate)
        else:
            result = duration_matching_loop(audio_data_b64=audio_b64, prompt=prompt,
                                             target_duration=source_duration, sample_rate=16000,
                                             initial_speech_rate=est_speech_rate)

        dubbed_dur = result.get("duration", 0)
        print(f"\n[dub]   Generated audio duration: {dubbed_dur:.2f}s")

        # ── Log this Seed Audio generation ──
        dur_err = abs(dubbed_dur - source_duration) / max(source_duration, 0.01) * 100
        append_log({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "video_source": os.path.basename(video_path),
            "target_language": target_lang,
            "source_language": source_lang,
            "chunk": None,
            "original_english_transcript": transcript,
            "seed_audio_prompt_french": prompt,
        "seed_audio_prompt_english": llm_result.get("prompt_english", ""),
            "translated_text_french": llm_result.get("translation", ""),
            "seed_audio_prompt_english": llm_result.get("prompt_english", ""),
            "duration_mismatch_pct": round(dur_err, 1),
            "source_duration_s": round(source_duration, 2),
            "generated_duration_s": round(dubbed_dur, 2),
            "model_params": {
                "model": SEED_AUDIO_MODEL,
                "speech_rate": est_speech_rate,
                "sample_rate": 16000,
                "format": "wav",
            },
            "seed21_emotion": llm_result.get("emotion", ""),
            "seed21_pace": llm_result.get("pace", ""),
            "seed21_speech_rate_est": est_speech_rate,
        })

        with open(final_audio, "wb") as f:
            f.write(base64.b64decode(result["audio_b64"]))
        print(f"[dub]   Saved: {final_audio}")

    # ── Final step: mux ──
    print("\n── Step 4: Muxing audio into video ──")
    mux_audio(video_path, final_audio, output_path)
    print(f"[dub]   Output: {output_path}")

    final_dur = ffprobe_duration(output_path)
    print(f"[dub]   Final video duration: {final_dur:.2f}s")
    print(f"[dub]   Done! ✓\n")

    import shutil
    shutil.rmtree(workdir, ignore_errors=True)
    return output_path


# ── CLI entrypoint ──────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Video Dubbing Pipeline — Seed 2.1 LLM + Seed Audio 1.0 + ffmpeg"
    )
    parser.add_argument("--video", required=True, help="Path to input video file")
    parser.add_argument("--target-lang", required=True,
                        help="Target language for dubbing (e.g. 'French', 'Chinese')")
    parser.add_argument("--source-lang", default="English",
                        help="Source language (default: English)")
    parser.add_argument("--transcript", default=None,
                        help="Verbatim transcript of source audio. Required for quality results.")
    parser.add_argument("--output", default=None,
                        help="Output video path (default: <input>_dubbed_<lang>.mp4)")
    parser.add_argument("--no-duration-loop", action="store_true",
                        help="Skip the duration matching loop (single generation)")
    args = parser.parse_args()

    run_pipeline(video_path=args.video, target_lang=args.target_lang,
                 source_lang=args.source_lang, transcript=args.transcript,
                 output_path=args.output, no_duration_loop=args.no_duration_loop)


if __name__ == "__main__":
    main()