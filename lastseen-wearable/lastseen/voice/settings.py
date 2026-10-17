"""The spoken voice setting: Mac `say` or a Grok voice. Persisted in data/settings.json."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from lastseen.voice.grok_tts import DEFAULT_VOICES

log = logging.getLogger("lastseen.voice")

MAC = "mac"
SAMPLE = "Are you looking for your AirPods?"


class VoiceSettings:
    def __init__(self, speaker, tts, path):
        self.speaker, self.tts, self.path = speaker, tts, Path(path)
        saved = self._load().get("voice", MAC)
        if not self.set_voice(saved, persist=False):
            self.speaker.voice = MAC

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except FileNotFoundError:
            return {}
        except Exception:
            log.exception("settings file unreadable; using defaults")
            return {}

    def _voices(self) -> list[dict]:
        out = [{"id": MAC, "label": "Mac (Samantha)", "disabled": False}]
        grok = self.tts.voices() if self.tts is not None else DEFAULT_VOICES
        suffix = "" if self.tts is not None else " (add XAI_API_KEY to .env)"
        out += [{"id": f"grok:{vid}", "label": f"Grok · {name}{suffix}", "disabled": self.tts is None}
                for vid, name in grok]
        return out

    def state(self) -> dict:
        return {"voice": self.speaker.voice, "voices": self._voices(), "grok": self.tts is not None}

    def set_voice(self, voice: str, persist: bool = True) -> bool:
        ok = any(v["id"] == voice and not v["disabled"] for v in self._voices())
        if not ok:
            return False
        self.speaker.voice = voice
        if persist:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps({**self._load(), "voice": voice}))
            except Exception:
                log.exception("could not save the voice setting")
        return True

    def test(self) -> None:
        self.speaker.say(SAMPLE)
