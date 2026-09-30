"""FFmpeg helpers — extract, mux, concat, probe."""

import json
import os
import subprocess


def duration(path: str) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "default=nw=1:nk=1", path],
                       capture_output=True, text=True, timeout=30)
    return float(r.stdout.strip())


def audio_info(path: str) -> dict:
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


def extract_audio(video_path: str, out_wav: str):
    """Extract first audio stream to 16 kHz mono WAV."""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-i", video_path,
                    "-vn", "-acodec", "pcm_s16le",
                    "-ar", "16000", "-ac", "1", out_wav],
                   check=True, timeout=600)


def extract_segment(video_path: str, out_wav: str,
                    start_sec: float, duration_sec: float):
    """Extract a segment of the first audio stream."""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-i", video_path,
                    "-vn", "-acodec", "pcm_s16le",
                    "-ar", "16000", "-ac", "1",
                    "-ss", str(start_sec), "-t", str(duration_sec),
                    out_wav],
                   check=True, timeout=300)


def mux(video_path: str, new_audio_path: str, output_path: str):
    """Replace original audio while keeping the video stream intact."""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-i", video_path, "-i", new_audio_path,
                    "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k",
                    "-shortest", output_path],
                   check=True, timeout=600)


def concat_wavs(input_wavs: list, output_wav: str):
    """Concatenate WAV files using ffmpeg concat demuxer (in-order)."""
    if len(input_wavs) == 0:
        raise RuntimeError("No WAVs to concatenate")
    if len(input_wavs) == 1:
        subprocess.run(["cp", input_wavs[0], output_wav], check=True)
        return
    concat_file = os.path.join(os.path.dirname(output_wav) or ".", "_concat_list.txt")
    with open(concat_file, "w") as f:
        for w in input_wavs:
            f.write(f"file '{os.path.abspath(w)}'\n")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-f", "concat", "-safe", "0",
                    "-i", concat_file,
                    "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                    output_wav],
                   check=True, timeout=600)
    os.remove(concat_file)