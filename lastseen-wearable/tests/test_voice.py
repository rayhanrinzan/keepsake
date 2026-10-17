import threading
import time

import numpy as np
import pytest

from lastseen.voice.listen import Listener
from lastseen.voice.speak import Speaker

SR = 16000


class FakeProc:
    def __init__(self, runner, text):
        self.runner, self.text = runner, text

    def wait(self, timeout=None):
        time.sleep(0.3)
        with self.runner.lock:
            self.runner.concurrent -= 1
        return 0

    def terminate(self):
        pass


class FakeRunner:
    def __init__(self):
        self.lock = threading.Lock()
        self.concurrent = 0
        self.max_concurrent = 0
        self.calls = []

    def __call__(self, cmd, **kw):
        with self.lock:
            self.concurrent += 1
            self.max_concurrent = max(self.max_concurrent, self.concurrent)
            self.calls.append(cmd[-1])
        return FakeProc(self, cmd[-1])


def wait_until(pred, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


def test_utterances_do_not_overlap():
    r = FakeRunner()
    sp = Speaker(runner=r)
    try:
        sp.say("one")
        sp.say("two")
        assert wait_until(lambda: len(r.calls) == 2 and not sp.speaking.is_set() and r.concurrent == 0)
        assert r.max_concurrent == 1 and r.calls == ["one", "two"]
    finally:
        sp.stop()


def test_speaking_flag_set_during_say():
    r = FakeRunner()
    sp = Speaker(runner=r)
    try:
        sp.say("x")
        time.sleep(0.05)
        assert sp.speaking.is_set()
        assert wait_until(lambda: not sp.speaking.is_set())
    finally:
        sp.stop()


def test_nonzero_exit_is_logged_not_raised(caplog):
    class BadProc(FakeProc):
        def wait(self, timeout=None):
            return 1

    class Nonzero(FakeRunner):
        def __call__(self, cmd, **kw):
            super().__call__(cmd)
            return BadProc(self, cmd[-1])

    sp = Speaker(runner=Nonzero())
    try:
        with caplog.at_level("WARNING"):
            sp.say("x")
            assert wait_until(lambda: sp.last_end > 0 and not sp.speaking.is_set())
        assert "code 1" in caplog.text
    finally:
        sp.stop()


def test_runner_exception_is_logged_not_raised():
    class Bad(FakeRunner):
        def __call__(self, cmd, **kw):
            raise OSError("no say")

    sp = Speaker(runner=Bad())
    try:
        sp.say("x")
        assert wait_until(lambda: not sp.speaking.is_set())
    finally:
        sp.stop()


class Clock:
    t = 100.0

    def __call__(self):
        return self.t


def block(n=SR // 4, v=0.1):
    return np.full(n, v, dtype=np.float32)


def make(transcript="where are my airpods", on_text=None):
    speaking = threading.Event()
    clock = Clock()
    got = []
    lst = Listener(on_text or (lambda t: got.append(t)), speaking,
                   transcribe=lambda audio: transcript, clock=clock)
    return lst, speaking, clock, got


def test_listener_drops_audio_while_speaking():
    lst, speaking, clock, _ = make()
    lst.feed(block())
    assert lst.buffer_len() > 0
    speaking.set()
    for _ in range(10):
        lst.feed(block())
    assert lst.buffer_len() == 0


def test_listener_drops_for_half_second_after_speaking():
    lst, speaking, clock, _ = make()
    speaking.set()
    lst.feed(block())
    speaking.clear()
    clock.t += 0.3
    lst.feed(block())
    assert lst.buffer_len() == 0
    clock.t += 0.3  # 0.6 s after clear
    lst.feed(block())
    assert lst.buffer_len() > 0


def test_transcript_delivered_and_buffer_cleared():
    lst, _, _, got = make()
    for _ in range(6):
        lst.feed(block())
    lst.evaluate()
    assert got == ["where are my airpods"]
    assert lst.buffer_len() == 0
    assert 'heard: "where are my airpods"' == lst.status


def test_status_not_updated_for_chatter():
    lst, _, _, _ = make(transcript="nice weather", on_text=lambda t: False)
    for _ in range(6):
        lst.feed(block())
    lst.evaluate()
    assert not lst.status.startswith("heard")


def test_identical_transcript_within_6s_ignored():
    lst, _, clock, got = make()
    for _ in range(6):
        lst.feed(block())
    lst.evaluate()
    clock.t += 3
    for _ in range(6):
        lst.feed(block())
    lst.evaluate()
    assert len(got) == 1
    clock.t += 4
    for _ in range(6):
        lst.feed(block())
    lst.evaluate()
    assert len(got) == 2


def test_silence_is_not_transcribed():
    lst, _, _, got = make()
    for _ in range(6):
        lst.feed(block(v=0.0))
    lst.evaluate()
    assert got == []


def test_empty_transcript_ignored():
    lst, _, _, got = make(transcript="  ")
    for _ in range(6):
        lst.feed(block())
    lst.evaluate()
    assert got == []


def test_on_text_false_keeps_buffer():
    lst, _, _, _ = make(on_text=lambda t: False)
    for _ in range(6):
        lst.feed(block())
    lst.evaluate()
    assert lst.buffer_len() > 0


def test_listener_failure_sets_off_status():
    def boom():
        raise RuntimeError("no mic")

    lst = Listener(lambda t: None, threading.Event(), open_stream=boom, transcribe=lambda a: "")
    lst.start()
    assert wait_until(lambda: lst.status.startswith("off:"))
    assert "no mic" in lst.status
    lst.stop()


def test_on_text_exception_does_not_escape():
    def bad(t):
        raise ValueError("x")

    lst, _, _, _ = make(on_text=bad)
    for _ in range(6):
        lst.feed(block())
    lst.evaluate()


@pytest.mark.models
def test_whisper_base_en_loads_and_transcribes_silence():
    from faster_whisper import WhisperModel

    m = WhisperModel("base.en", device="cpu", compute_type="int8", download_root="models/whisper")
    segs, _ = m.transcribe(np.zeros(SR, dtype=np.float32), language="en", beam_size=1, vad_filter=True)
    assert isinstance(" ".join(s.text for s in segs), str)


class InstantRunner(FakeRunner):
    def __call__(self, cmd, **kw):
        with self.lock:
            self.calls.append(cmd[-1])

        class P:
            def wait(self, timeout=None):
                return 0

            def terminate(self):
                pass

        return P()


def test_short_utterance_between_feeds_still_mutes_tail():
    clock = Clock()
    sp = Speaker(runner=InstantRunner(), clock=clock)
    lst = Listener(lambda t: None, sp.speaking, transcribe=lambda a: "", clock=clock,
                   muted_until=sp.muted_until)
    try:
        lst.feed(block())
        assert lst.buffer_len() > 0
        clock.t = 100.1
        sp.say("hi")
        assert wait_until(lambda: sp.last_end > 0 and not sp.speaking.is_set())
        clock.t = 100.3  # utterance entirely between two feeds; 0.2 s after it ended
        lst.feed(block())
        assert lst.buffer_len() == 0
        clock.t = 100.7
        lst.feed(block())
        assert lst.buffer_len() > 0
    finally:
        sp.stop()


def test_speaking_stays_set_across_queued_utterances():
    r = FakeRunner()
    sp = Speaker(runner=r)
    try:
        sp.say("one")
        sp.say("two")
        cleared_early = False
        end = time.time() + 3
        while time.time() < end:
            done = len(r.calls) == 2 and r.concurrent == 0
            if not sp.speaking.is_set() and not done:
                cleared_early = True
            if done and not sp.speaking.is_set():
                break
            time.sleep(0.002)
        assert not cleared_early
        assert not sp.speaking.is_set()
    finally:
        sp.stop()


def test_say_uses_double_dash():
    r = FakeRunner()
    cmds = []
    orig = r.__call__

    def spy(cmd, **kw):
        cmds.append(cmd)
        return orig(cmd)

    sp = Speaker(runner=spy)
    try:
        sp.say("-v evil")
        assert wait_until(lambda: cmds)
        assert list(cmds[0][-2:]) == ["--", "-v evil"]
    finally:
        sp.stop()


ITEMS = None


def _items():
    from lastseen.config import load_config

    return load_config("config.yaml").items


class FakeEngine:
    def __init__(self):
        self.asked = []

    def ask(self, q, source):
        self.asked.append((q, source))
        return {"text": f"answer {len(self.asked)}", "item_id": "airpods"}


def test_route_find_asks_and_speaks_chatter_discarded():
    from lastseen.voice.route import make_on_text

    eng, spoken = FakeEngine(), []

    class Sp:
        def say(self, t):
            spoken.append(t)

    on_text = make_on_text(eng, Sp(), _items())
    assert on_text("where are my airpods") is True
    assert eng.asked == [("where are my airpods", "voice")] and spoken == ["answer 1"]
    assert on_text("what a lovely day it is") is False
    assert len(eng.asked) == 1 and spoken == ["answer 1"]


def test_end_to_end_audio_while_speaking_never_transcribed_and_answers_queue():
    from lastseen.voice.route import make_on_text

    r = FakeRunner()
    sp = Speaker(runner=r)
    transcribed = []
    on_text = make_on_text(FakeEngine(), sp, _items())
    lst = Listener(on_text, sp.speaking, transcribe=lambda a: transcribed.append(1) or "where are my airpods",
                   muted_until=sp.muted_until)
    try:
        on_text("where are my airpods")
        on_text("where are my glasses")
        for _ in range(8):  # the room hears the speaker; nothing may be buffered
            lst.feed(block())
        lst.evaluate()
        assert transcribed == [] and lst.buffer_len() == 0
        assert wait_until(lambda: len(r.calls) == 2 and not sp.speaking.is_set())
        assert r.calls == ["answer 1", "answer 2"] and r.max_concurrent == 1
    finally:
        sp.stop()


def test_route_unknown_item_is_not_spoken():
    from lastseen.voice.route import make_on_text

    class Eng:
        asked = []

        def ask(self, q, source):
            self.asked.append(q)
            return {"text": "I'm not tracking anything called spoon yet.", "item_id": None}

    spoken, eng = [], Eng()

    class Sp:
        def say(self, t):
            spoken.append(t)

    assert make_on_text(eng, Sp(), _items())("where is my spoon") is True   # handled: buffer cleared
    assert eng.asked == ["where is my spoon"] and spoken == []


def test_dialog_gets_text_first():
    from lastseen.voice.route import make_on_text

    eng, spoken = FakeEngine(), []

    class Sp:
        def say(self, t):
            spoken.append(t)

    class Dialog:
        def on_text(self, text):
            return True

    on_text = make_on_text(eng, Sp(), _items(), dialog=Dialog())
    assert on_text("where are my airpods") is True
    assert eng.asked == [] and spoken == []


def test_dialog_declines_falls_through():
    from lastseen.voice.route import make_on_text

    eng, spoken = FakeEngine(), []

    class Sp:
        def say(self, t):
            spoken.append(t)

    class Dialog:
        def on_text(self, text):
            return False

    on_text = make_on_text(eng, Sp(), _items(), dialog=Dialog())
    assert on_text("where are my airpods") is True
    assert eng.asked == [("where are my airpods", "voice")]


def test_dialog_error_falls_through(caplog):
    from lastseen.voice.route import make_on_text

    eng, spoken = FakeEngine(), []

    class Sp:
        def say(self, t):
            spoken.append(t)

    class Dialog:
        def on_text(self, text):
            raise RuntimeError("boom")

    on_text = make_on_text(eng, Sp(), _items(), dialog=Dialog())
    assert on_text("where are my airpods") is True
    assert eng.asked == [("where are my airpods", "voice")]
    assert "dialog" in caplog.text
