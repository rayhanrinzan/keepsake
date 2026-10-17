"""Grok TTS client, Speaker voice routing and the persisted voice setting. No network."""
import io
import json
import threading
import time

from lastseen.voice.grok_tts import DEFAULT_VOICES, GrokTTS
from lastseen.voice.settings import VoiceSettings
from lastseen.voice.speak import Speaker


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeOpener:
    def __init__(self, body=b"MP3", voices=None, fail=False):
        self.body, self.voices, self.fail = body, voices, fail
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append(req)
        if self.fail:
            raise OSError("network down")
        if req.get_method() == "GET":
            return FakeResp(json.dumps({"voices": self.voices or []}).encode())
        return FakeResp(self.body)


class Runner:
    def __init__(self):
        self.cmds = []

    def __call__(self, cmd, **kw):
        self.cmds.append(list(cmd))

        class P:
            def wait(self_inner):
                return 0

            def terminate(self_inner):
                pass
        return P()


def wait_until(pred, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.01)
    return False


def test_synth_posts_documented_request():
    op = FakeOpener(body=b"ID3audio")
    tts = GrokTTS("k", opener=op)
    assert tts.synth("Are you looking for your AirPods?", "ara") == b"ID3audio"
    req = op.requests[0]
    assert req.full_url == "https://api.x.ai/v1/tts" and req.get_method() == "POST"
    assert req.get_header("Authorization") == "Bearer k"
    assert json.loads(req.data) == {"text": "Are you looking for your AirPods?", "voice_id": "ara",
                                    "language": "en"}


def test_voices_from_api_then_fallback():
    tts = GrokTTS("k", opener=FakeOpener(voices=[{"voice_id": "eve", "name": "Eve"},
                                                 {"voice_id": "rex", "name": "Rex"}]))
    assert tts.voices() == [("eve", "Eve"), ("rex", "Rex")]
    assert GrokTTS("k", opener=FakeOpener(fail=True)).voices() == DEFAULT_VOICES


def test_from_env_needs_key(monkeypatch, tmp_path):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    assert GrokTTS.from_env(dotenv_path=tmp_path / "none.env") is None
    monkeypatch.setenv("XAI_API_KEY", "abc")
    assert GrokTTS.from_env(dotenv_path=tmp_path / "none.env").api_key == "abc"


def test_speaker_plays_grok_audio_and_deletes_file(tmp_path):
    r = Runner()
    sp = Speaker(runner=r, tts=GrokTTS("k", opener=FakeOpener(body=b"MP3")), voice="grok:eve")
    try:
        sp.say("hello")
        assert wait_until(lambda: r.cmds and not sp.speaking.is_set())
        assert r.cmds[0][0] == "afplay" and r.cmds[0][-1].endswith(".mp3")
        assert not __import__("os").path.exists(r.cmds[0][-1])
    finally:
        sp.stop()


def test_speaker_falls_back_to_mac_voice_when_grok_fails():
    r = Runner()
    sp = Speaker(runner=r, tts=GrokTTS("k", opener=FakeOpener(fail=True)), voice="grok:eve")
    try:
        sp.say("hello")
        assert wait_until(lambda: r.cmds and not sp.speaking.is_set())
        assert r.cmds[0][0] == "say" and r.cmds[0][-1] == "hello"
    finally:
        sp.stop()


def test_speaker_mac_voice_by_default():
    r = Runner()
    sp = Speaker(runner=r)
    try:
        sp.say("hi")
        assert wait_until(lambda: r.cmds and not sp.speaking.is_set())
        assert r.cmds[0][0] == "say"
    finally:
        sp.stop()


def test_settings_lists_voices_and_persists(tmp_path):
    sp = Speaker(runner=Runner())
    try:
        tts = GrokTTS("k", opener=FakeOpener(voices=[{"voice_id": "eve", "name": "Eve"}]))
        vs = VoiceSettings(sp, tts, tmp_path / "settings.json")
        st = vs.state()
        assert st["voice"] == "mac" and st["grok"] is True
        assert [v["id"] for v in st["voices"]] == ["mac", "grok:eve"]
        assert vs.set_voice("grok:eve") is True and sp.voice == "grok:eve"
        assert vs.set_voice("grok:nobody") is False and sp.voice == "grok:eve"
        sp.voice = "mac"
        again = VoiceSettings(sp, tts, tmp_path / "settings.json")
        assert again.state()["voice"] == "grok:eve"
    finally:
        sp.stop()


def test_settings_without_key_offers_grok_voices_disabled(tmp_path):
    sp = Speaker(runner=Runner())
    try:
        vs = VoiceSettings(sp, None, tmp_path / "settings.json")
        st = vs.state()
        assert st["grok"] is False
        grok = [v for v in st["voices"] if v["id"].startswith("grok:")]
        assert [v["id"] for v in grok] == [f"grok:{i}" for i, _ in DEFAULT_VOICES]
        assert all(v["disabled"] for v in grok)
        assert vs.set_voice("grok:eve") is False and sp.voice == "mac"
    finally:
        sp.stop()


def test_saved_grok_voice_ignored_without_key(tmp_path):
    (tmp_path / "settings.json").write_text(json.dumps({"voice": "grok:rex"}))
    sp = Speaker(runner=Runner())
    try:
        VoiceSettings(sp, None, tmp_path / "settings.json")
        assert sp.voice == "mac"
    finally:
        sp.stop()


def test_test_voice_speaks_sample(tmp_path):
    sp = Speaker(runner=Runner())
    said = []
    sp.say = said.append
    try:
        VoiceSettings(sp, None, tmp_path / "s.json").test()
        assert said == ["Are you looking for your AirPods?"]
    finally:
        sp.stop()
