#!/usr/bin/env python3
"""CLI entry point for the dubbing pipeline."""

import argparse

from dubpkg import config
from dubpkg.pipeline import run


def main():
    parser = argparse.ArgumentParser(
        description="Video Dubbing Pipeline — Seed 2.1 LLM + Seed Audio 1.0 + ffmpeg"
    )
    parser.add_argument("--video", required=True, help="Input video file")
    parser.add_argument("--target-lang", required=True,
                        help="Target language (e.g. 'French', 'Chinese')")
    parser.add_argument("--source-lang", default="English",
                        help="Source language (default: English)")
    parser.add_argument("--output", default=None,
                        help="Output path (default: <input>_dubbed_<lang>.mp4)")
    parser.add_argument("--no-duration-loop", action="store_true",
                        help="Skip duration matching (single generation pass)")
    args = parser.parse_args()

    config.load_env()
    run(video_path=args.video, target_lang=args.target_lang,
        source_lang=args.source_lang, output_path=args.output,
        no_duration_loop=args.no_duration_loop)


if __name__ == "__main__":
    main()