"""Speech in: a pre-warmed mic stream, rolling buffer, faster-whisper on its own thread.

Approach ported from the prototype's SpeechListener (legacy/lastseen_demo.py). Audio is only ever held in
the rolling in-memory buffer; transcripts are handed to `on_text` and not kept.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable

import numpy as np

log = logging.getLogger("lastseen.voice")

SR = 16000
BLOCK_S = 0.25
BUFFER_S = 4.5
EVAL_EVERY_S = 1.5
SILENCE_RMS = 0.005
POST_SPEECH_MUTE_S = 0.5
DEDUPE_S = 6.0


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", text.lower()).strip()


class Listener:
    def __init__(self, on_text: Callable[[str], object], speaking: threading.Event, model: str = "base.en",
                 models_dir: str = "models/whisper", *, transcribe: Callable | None = None,
                 open_stream: Callable | None = None, clock: Callable[[], float] = time.monotonic,
                 on_status: Callable[[str], None] | None = None,
                 muted_until: Callable[[], float] | None = None):
        self.on_text = on_text
        self.speaking = speaking
        self.model_name = model
        self.models_dir = models_dir
        self._transcribe = transcribe
        self._open_stream = open_stream
        self._clock = clock
        self._on_status = on_status
        self._muted_until = muted_until
        self._lock = threading.Lock()
        self._buf: deque = deque(maxlen=int(SR * BUFFER_S))
        self._since = 0
        self._mute_until = 0.0
        self._last_norm = ""
        self._last_ts = -1e9
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._stream = None
        self._status = "starting"

    @property
    def status(self) -> str:
        return self._status

    @status.setter
    def status(self, value: str) -> None:
        self._status = value
        if self._on_status is not None:
            try:
                self._on_status(value)
            except Exception:
                log.exception("status callback failed")

    def buffer_len(self) -> int:
        with self._lock:
            return len(self._buf)

    def feed(self, block: np.ndarray) -> None:
        """Called from the audio callback; must stay cheap (no transcription here)."""
        now = self._clock()
        with self._lock:
            if self.speaking.is_set():
                self._buf.clear()
                self._since = 0
                self._mute_until = now + POST_SPEECH_MUTE_S
                return
            until = max(self._mute_until, self._muted_until() if self._muted_until else 0.0)
            if now < until:
                self._buf.clear()
                self._since = 0
                return
            self._buf.extend(block)
            self._since += len(block)
            ready = self._since >= SR * EVAL_EVERY_S
        if ready:
            self._wake.set()

    def evaluate(self) -> None:
        with self._lock:
            self._since = 0
            audio = np.array(self._buf, dtype=np.float32)
        if audio.size == 0 or float(np.sqrt(np.mean(audio**2))) < SILENCE_RMS:
            return
        try:
            text = self._transcribe(audio).strip()
        except Exception:
            log.exception("transcription failed")
            return
        if not text:
            return
        norm, now = _norm(text), self._clock()
        if norm == self._last_norm and now - self._last_ts < DEDUPE_S:
            self._clear()
            return
        self._last_norm, self._last_ts = norm, now
        keep = False
        try:
            keep = self.on_text(text) is False
            if not keep:
                self.status = f'heard: "{text[:50]}"'
        except Exception:
            log.exception("on_text failed")
        if not keep:
            self._clear()

    def _clear(self) -> None:
        with self._lock:
            self._buf.clear()
            self._since = 0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="listener", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        stream, self._stream = self._stream, None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=3.0)

    def _run(self) -> None:
        try:
            if self._transcribe is None:
                self._transcribe = self._load_whisper()
            self._stream = (self._open_stream or self._default_stream)()
            self.status = "listening"
        except Exception as e:
            log.exception("voice input unavailable")
            self.status = f"off: {e}"
            return
        while not self._stop.is_set():
            if not self._wake.wait(timeout=0.5):
                continue
            self._wake.clear()
            if self._stop.is_set():
                break
            try:
                self.evaluate()
            except Exception:
                log.exception("listener loop error")

    def _load_whisper(self):
        from faster_whisper import WhisperModel

        model = WhisperModel(self.model_name, device="cpu", compute_type="int8",
                             download_root=str(Path(self.models_dir)))

        def transcribe(audio: np.ndarray) -> str:
            segs, _ = model.transcribe(audio, language="en", beam_size=1, vad_filter=True)
            return " ".join(s.text for s in segs)

        return transcribe

    def _default_stream(self):
        import sounddevice as sd

        def cb(indata, frames, t, status):
            self.feed(indata[:, 0].copy())

        stream = sd.InputStream(samplerate=SR, channels=1, dtype="float32", callback=cb,
                                blocksize=int(SR * BLOCK_S))
        stream.start()
        return stream
