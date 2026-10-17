"""xAI Grok text-to-speech: text in, MP3 bytes out (https://docs.x.ai, Voice > Text to Speech).

Only the sentence to speak leaves the laptop. Uses the standard library so no new dependency.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
from pathlib import Path

log = logging.getLogger("lastseen.voice")

TTS_URL = "https://api.x.ai/v1/tts"
VOICES_URL = "https://api.x.ai/v1/tts/voices"
DEFAULT_VOICES = [("eve", "Eve"), ("ara", "Ara"), ("leo", "Leo"), ("rex", "Rex"), ("sal", "Sal")]


class GrokTTS:
    def __init__(self, api_key: str, timeout: float = 6.0, opener=urllib.request.urlopen):
        self.api_key = api_key
        self.timeout = timeout
        self._open = opener
        self._voices: list[tuple[str, str]] | None = None

    @classmethod
    def from_env(cls, dotenv_path=None) -> "GrokTTS | None":
        try:
            from dotenv import load_dotenv

            p = Path(dotenv_path) if dotenv_path else Path(".env")
            if p.is_file():
                load_dotenv(p, override=False)
        except ImportError:
            pass
        key = os.environ.get("XAI_API_KEY")
        return cls(key) if key else None

    def _request(self, url: str, body: dict | None = None) -> urllib.request.Request:
        req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                     method="POST" if body is not None else "GET")
        req.add_header("Authorization", f"Bearer {self.api_key}")
        if body is not None:
            req.add_header("Content-Type", "application/json")
        return req

    def synth(self, text: str, voice_id: str) -> bytes:
        """MP3 bytes for `text` in `voice_id`. Raises on any network or HTTP error."""
        req = self._request(TTS_URL, {"text": text, "voice_id": voice_id, "language": "en"})
        with self._open(req, timeout=self.timeout) as resp:
            return resp.read()

    def voices(self) -> list[tuple[str, str]]:
        """(voice_id, name) from the API, cached; the documented built-in voices if that fails."""
        if self._voices is None:
            try:
                with self._open(self._request(VOICES_URL), timeout=self.timeout) as resp:
                    data = json.loads(resp.read())
                found = [(str(v["voice_id"]), str(v.get("name") or v["voice_id"])) for v in data.get("voices", [])]
                self._voices = found or list(DEFAULT_VOICES)
            except Exception:
                log.warning("could not list Grok voices; using the built-in list")
                self._voices = list(DEFAULT_VOICES)
        return self._voices
