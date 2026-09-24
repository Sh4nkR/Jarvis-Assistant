"""Mouth: turns reply sentences into speech (Microsoft's free neural voices via edge-tts).

jaredrhod's backtalk uses Kokoro. Kokoro on Windows needs PyTorch (about 2 GB)
plus espeak-ng installed separately, so Jarvis uses edge-tts instead: small,
natural, British. If it can't reach the voice service, the window falls back
to the browser's built-in voice, so Jarvis never goes mute.
"""
import logging
import re
import time

from common import CFG

log = logging.getLogger("jarvis.mouth")

_CODE = re.compile(r"```.*?```", re.S)
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
_URL = re.compile(r"https?://\S+")
_MARK = re.compile(r"[*_`#>|]+")
_BULLET = re.compile(r"^\s*(?:[-•]|\d+[.)])\s+", re.M)


def for_speech(text: str) -> str:
    """What should be SAID for a chunk of reply text (markdown stripped)."""
    t = _CODE.sub(" I've put the code on screen. ", text)
    t = _LINK.sub(r"\1", t)
    t = _URL.sub("the link on screen", t)
    t = _BULLET.sub("", t)
    t = _MARK.sub("", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


class Mouth:
    def __init__(self):
        self.voice = CFG["voice"]
        self.rate = CFG["voice_rate"]
        self.status = "ready"
        self.error = ""
        self._retry_at = 0.0          # after a failure, don't re-try the service on every sentence

    async def synth(self, text: str) -> bytes | None:
        """MP3 bytes for one sentence, or None (the window then uses its own voice)."""
        said = for_speech(text)
        if not said:
            return None
        if time.monotonic() < self._retry_at:
            return None
        try:
            import edge_tts
            comm = edge_tts.Communicate(said, self.voice, rate=self.rate)
            buf = bytearray()
            async for chunk in comm.stream():
                if chunk.get("type") == "audio":
                    buf += chunk["data"]
            if buf:
                self.status = "ready"
                return bytes(buf)
            raise RuntimeError("voice service returned no audio")
        except Exception as e:
            if self.status != "fallback":
                log.warning("voice service unavailable, using the window's own voice: %s", e)
            self.status = "fallback"
            self.error = str(e)[:200]
            self._retry_at = time.monotonic() + 300     # try the service again in 5 minutes
            return None
