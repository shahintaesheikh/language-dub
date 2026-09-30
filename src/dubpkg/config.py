"""Config — env vars, constants, path helpers."""

import os

ENV_FILE = os.path.expanduser("/Users/bytedance/dhar/.env")
LOG_FILE = os.path.expanduser("/Users/bytedance/dhar/work/dub_log.json")

# Models
SEED21_MODEL = "dola-seed-2-1-turbo-260628"
SEED20_LITE_MODEL = "seed-2-0-lite-260428"
SEED_AUDIO_MODEL = "seed-audio-1.0"

# Endpoints
SEED_AUDIO_URL = "https://voice.ap-southeast-1.bytepluses.com/api/v3/tts/create"
MODELARK_CHAT_URL = "https://ark.ap-southeast.bytepluses.com/api/v3/chat/completions"

# Tuning
MAX_SPEECH_ADJUST_ITERATIONS = 3
DURATION_TOLERANCE = 0.15          # ±15%
CHUNK_THRESHOLD = 90               # seconds — above this we chunk
CHUNK_MAX_DURATION = 60            # seconds per chunk
REF_AUDIO_MAX_SEC = 30             # max reference audio for Seed Audio
ASR_MAX_BYTES = 5_000_000          # ~5 MB threshold for chunked ASR

# API keys (lazy-loaded)
ARK_API_KEY: str | None = None
SPEECH_API_KEY: str | None = None


def load_env():
    """Read API keys from .env file into module globals."""
    global ARK_API_KEY, SPEECH_API_KEY
    if not os.path.exists(ENV_FILE):
        print(f"[dub] Error: {ENV_FILE} not found.")
        raise SystemExit(1)
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line.startswith("ARK_API_KEY="):
                ARK_API_KEY = line.split("=", 1)[1].strip('"').strip("'")
            elif line.startswith("SPEECH_API_KEY="):
                SPEECH_API_KEY = line.split("=", 1)[1].strip('"').strip("'")
    if not ARK_API_KEY or not SPEECH_API_KEY:
        print(f"[dub] Error: ARK_API_KEY and SPEECH_API_KEY must be set in {ENV_FILE}")
        raise SystemExit(1)