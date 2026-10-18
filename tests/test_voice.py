"""Voice settings and the Grok TTS proxy. Grok itself is never called: the client is faked."""
import importlib

import pytest
from fastapi.testclient import TestClient

from voice import DEFAULT_VOICES, TTSError, load_env_file


class FakeGrok:
    def __init__(self, fail: str | None = None):
        self.calls, self.fail = [], fail

    def voices(self):
        return [{"voice_id": "eve", "name": "Eve"}, {"voice_id": "rex", "name": "Rex"}]

    def synthesize(self, text, voice_id, speed):
        if self.fail:
            raise TTSError(self.fail)
        self.calls.append((text, voice_id, speed))
        return b"ID3fake-mp3"


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("CTRLF_CAMERA_ENABLED", "0")
    monkeypatch.setenv("CTRLF_DB_PATH", str(tmp_path / "api.db"))
    monkeypatch.setenv("CTRLF_SNAPSHOT_DIR", str(tmp_path / "snaps"))
    monkeypatch.setenv("CTRLF_ENV_FILE", str(tmp_path / "missing.env"))  # never read the real key
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    import main
    main = importlib.reload(main)
    with TestClient(main.app) as c:
        yield c, main


def test_defaults_to_browser_voice_without_a_key(api):
    c, _ = api
    v = c.get("/api/voice").json()
    assert v["provider"] == "browser" and v["grok_available"] is False
    assert v["voice_id"] == "eve" and v["speed"] == 1.0
    assert [x["voice_id"] for x in v["voices"]] == [x["voice_id"] for x in DEFAULT_VOICES]
    assert c.post("/api/tts", json={"text": "hi"}).status_code == 503


def test_voice_settings_persist_and_tts_uses_them(api):
    c, main = api
    main.grok = fake = FakeGrok()
    assert c.get("/api/voice").json()["grok_available"] is True
    r = c.put("/api/voice", json={"provider": "grok", "voice_id": "rex", "speed": 0.9})
    assert r.status_code == 200 and r.json()["voice_id"] == "rex"
    assert main.db.get_setting("voice_id") == "rex"  # stored, survives restarts

    r = c.post("/api/tts", json={"text": "Your keys are on the desk."})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg"
    assert r.content == b"ID3fake-mp3"
    assert fake.calls == [("Your keys are on the desk.", "rex", 0.9)]

    c.post("/api/tts", json={"text": "Preview", "voice_id": "eve", "speed": 1.2})  # Settings preview
    assert fake.calls[-1] == ("Preview", "eve", 1.2)


def test_bad_settings_are_rejected(api):
    c, _ = api
    assert c.put("/api/voice", json={"provider": "robot", "voice_id": "eve", "speed": 1}).status_code == 422
    assert c.put("/api/voice", json={"provider": "grok", "voice_id": "eve", "speed": 3}).status_code == 422
    assert c.put("/api/voice", json={"provider": "grok", "voice_id": "", "speed": 1}).status_code == 422
    assert c.post("/api/tts", json={"text": "   "}).status_code == 422


def test_grok_errors_become_502_so_the_app_falls_back(api):
    c, main = api
    main.grok = FakeGrok(fail="Grok rejected the API key")
    r = c.post("/api/tts", json={"text": "hi"})
    assert r.status_code == 502 and "API key" in r.json()["detail"]


def test_env_file_loader_never_overrides_real_env(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("# comment\nXAI_API_KEY=from-file\nOTHER_THING='quoted'\n")
    monkeypatch.setenv("XAI_API_KEY", "from-shell")
    monkeypatch.delenv("OTHER_THING", raising=False)
    load_env_file(f)
    import os
    assert os.environ["XAI_API_KEY"] == "from-shell" and os.environ["OTHER_THING"] == "quoted"


def test_env_file_loader_strips_inline_comments(tmp_path, monkeypatch):
    """`.env.example` puts comments after values; copied as-is they must not end up in the value."""
    f = tmp_path / ".env"
    f.write_text("XAI_API_KEY=xai-abc123          # xai-… key from console.x.ai\n"
                 "CTRLF_CONFIDENCE=0.4  # minimum YOLO confidence\n"
                 "HASH_IN_QUOTES='a # b'\n"
                 "export CTRLF_CAMERA_NAME=iPhone\n"
                 "EMPTY=        # nothing set\n")
    for k in ("XAI_API_KEY", "CTRLF_CONFIDENCE", "HASH_IN_QUOTES", "CTRLF_CAMERA_NAME", "EMPTY"):
        monkeypatch.delenv(k, raising=False)
    load_env_file(f)
    import os
    assert os.environ["XAI_API_KEY"] == "xai-abc123"
    assert float(os.environ["CTRLF_CONFIDENCE"]) == 0.4
    assert os.environ["HASH_IN_QUOTES"] == "a # b"
    assert os.environ["CTRLF_CAMERA_NAME"] == "iPhone"
    assert os.environ["EMPTY"] == ""
