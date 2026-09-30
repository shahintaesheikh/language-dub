"""Pipeline — orchestration: ASR → LLM → Seed Audio → mux, with chunking."""

import base64
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import audio, asr, config, llm, log, seed_audio_api


def _run_short(video_path: str, source_lang: str, target_lang: str,
               transcript: str, workdir: str, no_duration_loop: bool):
    """Single-pass dubbing for short clips (≤ CHUNK_THRESHOLD s)."""
    source_duration = audio.duration(video_path)

    with open(os.path.join(workdir, "source_audio.wav"), "rb") as f:
        audio_b64 = base64.b64encode(f.read()).decode()

    print("\n── Step 2: LLM prompt generation (Seed 2.1) ──")
    print(f"[dub]   Model: {config.SEED21_MODEL}")
    llm_result = llm.generate_prompt(
        transcript=transcript,
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

    print("\n── Step 3: Seed Audio generation ──")
    print(f"[dub]   Model: {config.SEED_AUDIO_MODEL}")
    print(f"[dub]   Target duration: {source_duration:.2f}s")

    final_audio = os.path.join(workdir, "dubbed_audio.wav")
    if no_duration_loop:
        result = seed_audio_api.generate(audio_data_b64=audio_b64, prompt=prompt,
                                          speech_rate=est_speech_rate)
    else:
        result = seed_audio_api.duration_matching_loop(
            audio_data_b64=audio_b64, prompt=prompt,
            target_duration=source_duration, sample_rate=16000,
            initial_speech_rate=est_speech_rate)

    dubbed_dur = result.get("duration", 0)
    print(f"\n[dub]   Generated audio duration: {dubbed_dur:.2f}s")
    with open(final_audio, "wb") as f:
        f.write(base64.b64decode(result["audio_b64"]))
    print(f"[dub]   Saved: {final_audio}")

    # Log
    dur_err = abs(dubbed_dur - source_duration) / max(source_duration, 0.01) * 100
    log.append({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "video_source": os.path.basename(video_path),
        "target_language": target_lang,
        "source_language": source_lang,
        "chunk": None,
        "original_english_transcript": transcript,
        "seed_audio_prompt_french": prompt,
        "seed_audio_prompt_english": llm_result.get("prompt_english", ""),
        "translated_text_french": llm_result.get("translation", ""),
        "duration_mismatch_pct": round(dur_err, 1),
        "source_duration_s": round(source_duration, 2),
        "generated_duration_s": round(dubbed_dur, 2),
        "model_params": {
            "model": config.SEED_AUDIO_MODEL,
            "speech_rate": est_speech_rate,
            "sample_rate": 16000,
            "format": "wav",
        },
        "seed21_emotion": llm_result.get("emotion", ""),
        "seed21_pace": llm_result.get("pace", ""),
        "seed21_speech_rate_est": est_speech_rate,
    })

    return final_audio


def _chunk_worker(args):
    """Worker for parallel chunk dubbing."""
    (video_path, source_lang, target_lang,
     chunk_transcript, start_sec, end_sec, seg_dur,
     i, num_chunks, ref_b64,
     no_duration_loop, workdir) = args

    _b64 = __import__("base64")

    print(f"[dub]   Chunk {i + 1}: worker starting ({start_sec:.1f}s–{end_sec:.1f}s)")

    # LLM prompt for this chunk
    llm_result = llm.generate_prompt(
        transcript=chunk_transcript or f"[Chunk {i+1} of {num_chunks}, {seg_dur:.1f}s, no transcript]",
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
        result = seed_audio_api.generate(audio_data_b64=ref_b64, prompt=prompt,
                                          speech_rate=est_speech_rate)
    else:
        result = seed_audio_api.duration_matching_loop(
            audio_data_b64=ref_b64, prompt=prompt,
            target_duration=seg_dur, sample_rate=16000,
            initial_speech_rate=est_speech_rate)

    dubbed_dur = result.get("duration", 0)
    dur_err = abs(dubbed_dur - seg_dur) / max(seg_dur, 0.01) * 100

    # Log
    log.append({
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
        "translated_text_french": llm_result.get("translation", ""),
        "duration_mismatch_pct": round(dur_err, 1),
        "source_duration_s": round(seg_dur, 2),
        "generated_duration_s": round(dubbed_dur, 2),
        "model_params": {
            "model": config.SEED_AUDIO_MODEL,
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

    print(f"[dub]   Chunk {i + 1}: done, duration={dubbed_dur:.1f}s")
    return (i, chunk_wav)


def _run_long(video_path: str, source_lang: str, target_lang: str,
              workdir: str, no_duration_loop: bool):
    """Chunked dubbing for long clips (> CHUNK_THRESHOLD s)."""
    source_duration = audio.duration(video_path)
    num_chunks = max(1, int(source_duration / config.CHUNK_MAX_DURATION) +
                     (1 if source_duration % config.CHUNK_MAX_DURATION > 0 else 0))
    chunk_dur = source_duration / num_chunks

    print(f"[dub] Long audio ({source_duration:.0f}s): splitting into {num_chunks} "
          f"chunks of ~{chunk_dur:.1f}s each")

    # Prepare chunk args (ASR + ref audio per chunk)
    chunk_args = []
    for i in range(num_chunks):
        start_sec = i * chunk_dur
        end_sec = min((i + 1) * chunk_dur, source_duration)
        seg_dur = end_sec - start_sec

        # Extract segment audio
        seg_wav = os.path.join(workdir, f"chunk{i}_audio.wav")
        audio.extract_segment(video_path, seg_wav, start_sec, seg_dur)

        # ASR this chunk independently (avoids 413 on full 27-min audio)
        print(f"[dub]   Chunk {i + 1}: ASR {seg_dur:.0f}s segment...")
        asr_result = asr.transcribe(seg_wav, source_lang=source_lang)
        chunk_transcript = asr_result["text"]

        # Reference audio (first 30 s of chunk)
        ref_dur = min(seg_dur, config.REF_AUDIO_MAX_SEC)
        ref_wav = os.path.join(workdir, f"chunk{i}_ref.wav")
        audio.extract_segment(video_path, ref_wav, start_sec, ref_dur)
        with open(ref_wav, "rb") as f:
            ref_b64 = base64.b64encode(f.read()).decode()

        print(f"[dub]   Chunk {i + 1} ref: {os.path.getsize(ref_wav)} bytes, "
              f"transcript: {len(chunk_transcript)} chars")

        chunk_args.append((video_path, source_lang, target_lang,
                           chunk_transcript, start_sec, end_sec, seg_dur,
                           i, num_chunks, ref_b64,
                           no_duration_loop, workdir))

    # Dub all chunks in parallel
    print(f"[dub] Dubbing {len(chunk_args)} chunks with up to 4 parallel workers...")
    results = [None] * num_chunks
    with ThreadPoolExecutor(max_workers=4) as pool:
        fut_to_idx = {pool.submit(_chunk_worker, a): a[7] for a in chunk_args}
        for fut in as_completed(fut_to_idx):
            idx, chunk_wav = fut.result()
            results[idx] = chunk_wav

    # Stitch
    print(f"\n── Stitching {len(results)} chunks ──")
    stitched_wav = os.path.join(workdir, "stitched_audio.wav")
    audio.concat_wavs(results, stitched_wav)
    stitched_dur = audio.duration(stitched_wav)
    print(f"[dub]   Stitched audio duration: {stitched_dur:.1f}s "
          f"(target: {source_duration:.1f}s)")

    return stitched_wav


def run(video_path: str, target_lang: str, source_lang: str = "English",
        output_path: str = None, no_duration_loop: bool = False):
    """Execute the full dubbing pipeline."""
    print("\n" + "=" * 60)
    print("  Video Dubbing Pipeline")
    print(f"  Input:   {video_path}")
    print(f"  Target:  {target_lang}")
    print("=" * 60 + "\n")

    if not os.path.exists(video_path):
        print(f"[dub] Error: video not found: {video_path}")
        sys.exit(1)

    workdir = tempfile.mkdtemp(prefix="dub_")
    print(f"[dub] Working directory: {workdir}")

    if output_path is None:
        base = os.path.splitext(os.path.basename(video_path))[0]
        output_path = f"{base}_dubbed_{target_lang.lower()}.mp4"
    print(f"[dub] Output: {output_path}")

    # Step 0: Analyze
    print("\n── Step 0: Analyzing source video ──")
    src_dur = audio.duration(video_path)
    info = audio.audio_info(video_path)
    print(f"[dub]   Video duration: {src_dur:.2f}s")
    print(f"[dub]   Audio: {info}")

    # Step 1: Extract audio
    print("\n── Step 1: Extracting source audio ──")
    src_wav = os.path.join(workdir, "source_audio.wav")
    audio.extract_audio(video_path, src_wav)
    print(f"[dub]   Extracted: {src_wav}")

    # Branch: short vs long
    if src_dur > config.CHUNK_THRESHOLD:
        print(f"\n── Long-form mode (>{config.CHUNK_THRESHOLD}s) ──")
        final_audio = _run_long(video_path, source_lang, target_lang,
                                workdir, no_duration_loop)
    else:
        print(f"\n── Short-form mode (≤{config.CHUNK_THRESHOLD}s) ──")
        # Step 1b: ASR
        print("\n── Step 1b: ASR ──")
        print(f"[dub]   Language: {source_lang}")
        asr_result = asr.transcribe(src_wav, source_lang=source_lang)
        transcript = asr_result["text"]

        final_audio = _run_short(video_path, source_lang, target_lang,
                                 transcript, workdir, no_duration_loop)

    # Step 4: Mux
    print("\n── Step 4: Muxing audio into video ──")
    audio.mux(video_path, final_audio, output_path)
    print(f"[dub]   Output: {output_path}")

    final_dur = audio.duration(output_path)
    print(f"[dub]   Final video duration: {final_dur:.2f}s")
    print(f"[dub]   Done! ✓\n")

    import shutil
    shutil.rmtree(workdir, ignore_errors=True)
    return output_path