"""Speech out: a queue of utterances spoken one at a time, through macOS `say` or a Grok voice.

A Grok voice (`voice="grok:<id>"`) fetches MP3 from xAI and plays it with `afplay`; any failure
falls back to `say` so the room never goes silent.
"""
from __future__ import annotations

import logging
import queue
import os
import subprocess
import tempfile
import threading
import time

log = logging.getLogger("lastseen.voice")


class Speaker:
    def __init__(self, cmd=("say", "-v", "Samantha", "-r", "165"), runner=subprocess.Popen,
                 clock=time.monotonic, tail_s: float = 0.5, tts=None, voice: str = "mac"):
        self.cmd = tuple(cmd)
        self.tts = tts
        self.voice = voice
        self.runner = runner
        self._clock = clock
        self.tail_s = tail_s
        self.last_end = -1e9
        self._pending = 0
        self._lock = threading.Lock()
        self.speaking = threading.Event()
        self._q: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._proc = None
        self._thread = threading.Thread(target=self._run, name="speaker", daemon=True)
        self._thread.start()

    def say(self, text: str) -> None:
        if text and text.strip():
            with self._lock:
                self._pending += 1
                self.speaking.set()  # set before the worker starts so the mic never sees a gap
            self._q.put(text)

    def muted_until(self) -> float:
        """Mic stays muted until this time (end of the last utterance + tail)."""
        return self.last_end + self.tail_s

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                text = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                if not self._speak_grok(text):
                    self._play([*self.cmd, "--", text])
            except Exception:
                log.exception("speech failed")
            finally:
                self._proc = None
                with self._lock:
                    self.last_end = self._clock()
                    self._pending -= 1
                    if self._pending <= 0:
                        self._pending = 0
                        self.speaking.clear()

    def _play(self, cmd: list[str]) -> None:
        self._proc = self.runner(cmd)
        code = self._proc.wait()
        if code:
            log.warning("%s exited with code %s", cmd[0], code)

    def _speak_grok(self, text: str) -> bool:
        """True if a Grok voice spoke `text`; False means fall back to `say`."""
        voice = self.voice
        if self.tts is None or not voice.startswith("grok:"):
            return False
        try:
            audio = self.tts.synth(text, voice.split(":", 1)[1])
        except Exception as e:
            log.warning("Grok voice failed (%s); using the Mac voice", e)
            return False
        fd, path = tempfile.mkstemp(suffix=".mp3", prefix="lastseen-tts-")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(audio)
            self._play(["afplay", path])
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        return True

    def stop(self) -> None:
        self._stop.set()
        proc = self._proc
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
        self._thread.join(timeout=2.0)
