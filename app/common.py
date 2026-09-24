"""Shared paths, settings and logging for Jarvis."""
import json
import logging
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent          # Jarvis-Assistant/app
ROOT = APP.parent                              # Jarvis-Assistant
MEMORY = ROOT / "memory"                       # the brain's home folder (its vault)
MODELS = ROOT / "models"                       # speech model lives here, not in your user profile
LOGS = ROOT / "logs"
TMP = ROOT / "logs" / "tmp"
IS_WIN = sys.platform == "win32"

DEFAULTS = {
    "name": "JARVIS",
    "call_me": "Dr Wolf",
    "port": 8795,
    "face": "board",
    "voice": "en-GB-RyanNeural",
    "voice_rate": "+0%",
    "stt_model": "small.en",
    "model": "",
    "hands_on_at_start": True,
    "open_window": True,
}


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        cfg.update(json.loads((APP / "jarvis.json").read_text(encoding="utf-8")))
    except (OSError, ValueError) as e:
        print(f"  (jarvis.json unreadable, using defaults: {e})")
    return cfg


CFG = load_config()


def setup_logging() -> logging.Logger:
    LOGS.mkdir(parents=True, exist_ok=True)
    TMP.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fh = logging.FileHandler(LOGS / "jarvis.log", encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    root.addHandler(ch)
    for noisy in ("aiohttp.access", "httpx", "faster_whisper", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return logging.getLogger("jarvis")
