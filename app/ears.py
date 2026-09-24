"""Ears: local speech-to-text with faster-whisper (the engine backtalk uses).

Runs on the CPU in int8, so it needs no graphics drivers. The model downloads
once (about 480 MB for small.en) into Jarvis-Assistant/models.
"""
import logging
import threading
import time
import uuid

from common import CFG, MODELS, TMP

log = logging.getLogger("jarvis.ears")


class Ears:
    def __init__(self):
        self.name = CFG["stt_model"]
        self.model = None
        self.status = "loading"
        self.error = ""
        self._lock = threading.Lock()

    def load(self):
        """Blocking. Called once in a background thread at startup."""
        try:
            from faster_whisper import WhisperModel
            MODELS.mkdir(parents=True, exist_ok=True)
            t0 = time.time()
            self.model = WhisperModel(self.name, device="cpu", compute_type="int8",
                                      download_root=str(MODELS))
            self.status = "ready"
            log.info("ears ready (%s, %.1fs)", self.name, time.time() - t0)
        except Exception as e:
            self.status = "error"
            self.error = str(e)[:300]
            log.exception("ears failed to load")

    def transcribe(self, audio: bytes, suffix: str = ".webm") -> str:
        """Blocking. audio = whatever the browser recorded (webm/opus)."""
        if self.model is None:
            raise RuntimeError("ears are still loading" if self.status == "loading"
                               else f"ears unavailable: {self.error}")
        TMP.mkdir(parents=True, exist_ok=True)
        path = TMP / f"heard-{uuid.uuid4().hex}{suffix}"
        path.write_bytes(audio)
        try:
            with self._lock:
                lang = "en" if self.name.endswith(".en") else None
                try:
                    segs, _ = self.model.transcribe(str(path), beam_size=1, language=lang,
                                                    vad_filter=True)
                    text = " ".join(s.text.strip() for s in segs)
                except Exception:
                    # the silence trimmer is optional; never lose a sentence over it
                    segs, _ = self.model.transcribe(str(path), beam_size=1, language=lang)
                    text = " ".join(s.text.strip() for s in segs)
            return text.strip()
        finally:
            try:
                path.unlink()
            except OSError:
                pass
