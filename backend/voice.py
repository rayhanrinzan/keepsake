"""Spoken answers in a Grok voice (xAI Text to Speech), proxied so the API key stays on this computer.

Docs: https://docs.x.ai/developers/model-capabilities/audio/text-to-speech
  POST https://api.x.ai/v1/tts {text, voice_id, language, speed 0.7–1.5} -> raw MP3 bytes
  GET  https://api.x.ai/v1/tts/voices -> {"voices": [{voice_id, name, language}, ...]}
The key (XAI_API_KEY, from console.x.ai) is read from the environment or the repo's .env.
Only the sentence being spoken is sent to xAI. If Grok fails, the app falls back to the browser voice.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import httpx

log = logging.getLogger("keepsake.voice")

API = "https://api.x.ai/v1"
# Built-in voices named in xAI's TTS docs; used until (or if) the live list can't be fetched.
DEFAULT_VOICES = [{"voice_id": v, "name": v.title()} for v in ("eve", "ara", "rex", "sal", "leo")]
PROVIDERS = ("browser", "grok")
SPEED_RANGE = (0.7, 1.5)


class TTSError(Exception):
    """A Grok TTS failure, worded for the person using the app."""


def load_env_file(path: str | Path) -> None:
    """Minimal .env reader (KEY=value lines). Variables already set in the shell win."""
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


class GrokTTS:
    def __init__(self, api_key: str, timeout: float = 15.0):
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self.timeout = timeout
        self._voices: list[dict] | None = None
        self._voices_at = 0.0

    def voices(self) -> list[dict]:
        """Live voice list, cached for 10 minutes; the built-in list if it can't be fetched."""
        if self._voices is not None and time.monotonic() - self._voices_at < 600:
            return self._voices
        try:
            r = httpx.get(f"{API}/tts/voices", headers=self._headers, timeout=5.0)
            r.raise_for_status()
            found = [{"voice_id": v["voice_id"], "name": v.get("name") or v["voice_id"].title()}
                     for v in r.json().get("voices", []) if v.get("voice_id")]
            self._voices = found or DEFAULT_VOICES
        except Exception as e:  # noqa: BLE001
            log.warning("couldn't list Grok voices: %s", e)
            self._voices = DEFAULT_VOICES
        self._voices_at = time.monotonic()
        return self._voices

    def synthesize(self, text: str, voice_id: str, speed: float) -> bytes:
        try:
            r = httpx.post(f"{API}/tts", headers=self._headers, timeout=self.timeout,
                           json={"text": text, "voice_id": voice_id, "language": "en", "speed": speed})
        except httpx.HTTPError as e:
            raise TTSError(f"Couldn't reach Grok: {e.__class__.__name__}") from e
        if r.status_code == 200:
            return r.content
        if r.status_code in (400, 401, 403) and "key" in r.text.lower():
            raise TTSError("Grok rejected the API key. Use an xai- key from console.x.ai.")
        if r.status_code == 404:
            raise TTSError(f'Grok has no voice "{voice_id}".')
        if r.status_code == 429:
            raise TTSError("Grok is rate limiting requests. Try again in a moment.")
        raise TTSError(f"Grok TTS error {r.status_code}")
