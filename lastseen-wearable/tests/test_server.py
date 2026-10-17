import pytest
from fastapi.testclient import TestClient

from lastseen.bus import Bus
from lastseen.config import load_config
from lastseen.memory.store import Store
from lastseen.server.app import AppContext, create_app
from tests.fakes import FakeCamera, solid_frame


@pytest.fixture
def ctx(tmp_path):
    cfg = load_config("config.yaml")
    cfg.paths.data = str(tmp_path)
    bus = Bus()
    store = Store(str(tmp_path / "lastseen.db"), bus)
    return AppContext(cfg=cfg, bus=bus, store=store, camera=FakeCamera(solid_frame()),
                      metrics={"vision_tps": 3.0, "last_event_ts": None})


def client(ctx):
    return TestClient(create_app(ctx))


def test_health_reports_camera(ctx):
    r = client(ctx).get("/health")
    j = r.json()
    assert r.status_code == 200 and j["camera_fps"] == 30.0 and j["camera_ok"] is True
    for k in ("vision_tps", "detector_ms", "clip_ms", "hands_ms", "last_event_ts", "mic", "chalk"):
        assert k in j


def test_health_html(ctx):
    r = client(ctx).get("/health.html")
    assert r.status_code == 200 and "/health" in r.text


def test_ws_forwards_bus(ctx):
    with client(ctx).websocket_connect("/ws") as ws:
        ctx.bus.publish("show_answer", answer={"text": "hi"})
        m = ws.receive_json()
        assert m["type"] == "show_answer" and m["answer"]["text"] == "hi"


def _wait(cond, timeout=2.0):
    import time
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def test_ws_unsubscribes_when_idle(ctx):
    with client(ctx).websocket_connect("/ws"):
        assert _wait(lambda: ctx.bus.subscriber_count() == 1)
    assert _wait(lambda: ctx.bus.subscriber_count() == 0)


def test_health_camera_down(ctx):
    ctx.camera = FakeCamera(None, ok=False, fps=0)
    j = client(ctx).get("/health").json()
    assert j["camera_ok"] is False and j["camera_fps"] == 0


def test_ask_503_without_engine(ctx):
    r = client(ctx).post("/api/ask", json={"question": "x", "source": "dashboard"})
    assert r.status_code == 503 and "not available" in r.json()["detail"]


def test_ask_calls_fn(ctx):
    calls = []
    ctx.ask_fn = lambda q, s: calls.append((q, s)) or {"text": "ok"}
    r = client(ctx).post("/api/ask", json={"question": "where?"})
    assert r.json() == {"text": "ok"} and calls == [("where?", "dashboard")]


def test_enroll_503_and_calls(ctx):
    c = client(ctx)
    body = {"item_id": "a", "display_name": "A"}
    assert c.post("/api/enroll", json=body).status_code == 503
    assert c.post("/api/enroll/click", json={**body, "x": 1, "y": 2}).status_code == 503
    ctx.enroll_fn = lambda **kw: {"got": kw}
    assert c.post("/api/enroll", json=body).json()["got"]["item_id"] == "a"
    assert c.post("/api/enroll/click", json={**body, "x": 1, "y": 2}).json()["got"]["x"] == 1


def test_static_pages(ctx):
    c = client(ctx)
    assert c.get("/frame").status_code == 200
    assert c.get("/dashboard").status_code == 200


def test_clips_static(ctx, tmp_path):
    c = client(ctx)
    (tmp_path / "clips" / "a.txt").write_text("hi")
    assert c.get("/clips/a.txt").text == "hi"


@pytest.fixture
def live(ctx):
    """Real uvicorn on an ephemeral port: TestClient buffers infinite streams."""
    import socket
    import threading
    import time

    import uvicorn

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(ctx), log_level="warning"))
    t = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    t.start()
    deadline = time.time() + 10
    while not server.started:
        assert time.time() < deadline, "server failed to start"
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(5)
    assert not t.is_alive()


def _first_part(base):
    import httpx
    buf = b""
    with httpx.stream("GET", base + "/stream", timeout=10) as r:
        assert r.headers["content-type"].startswith("multipart/x-mixed-replace")
        for chunk in r.iter_bytes():
            buf += chunk
            if b"--frame" in buf and b"\xff\xd9" in buf:
                break
    return buf


def test_stream_serves_jpeg(live):
    buf = _first_part(live)
    assert b"image/jpeg" in buf and b"\xff\xd8" in buf


def test_stream_placeholder(ctx, live):
    ctx.camera.frame = None
    assert b"\xff\xd8" in _first_part(live)


def test_stream_overlay(ctx, live):
    seen = []
    ctx.overlay_fn = lambda f: seen.append(1) or f.copy()
    _first_part(live)
    assert seen


def test_stream_stops_after_disconnect(ctx, live):
    calls = []
    ctx.overlay_fn = lambda f: calls.append(1) or f.copy()
    _first_part(live)
    import time
    time.sleep(0.5)
    n = len(calls)
    time.sleep(0.7)
    assert len(calls) == n


def test_forget_503_and_calls(ctx):
    c = client(ctx)
    assert c.post("/api/forget", json={"item_id": "airpods"}).status_code == 503
    calls = []
    ctx.forget_fn = lambda item_id: calls.append(item_id) or {"ok": True}
    r = c.post("/api/forget", json={"item_id": "airpods"})
    assert r.status_code == 200 and r.json() == {"ok": True} and calls == ["airpods"]
    assert c.post("/api/forget", json={}).status_code == 422


def test_dismiss_endpoint(ctx):
    calls = []
    ctx.dismiss_fn = lambda item_id: calls.append(item_id) or {"ok": True}
    r = client(ctx).post("/api/dismiss", json={"item_id": "airpods"})
    assert r.status_code == 200 and r.json() == {"ok": True} and calls == ["airpods"]


def test_dismiss_unavailable(ctx):
    assert client(ctx).post("/api/dismiss", json={"item_id": "airpods"}).status_code == 503


def test_dismiss_bad_id(ctx):
    ctx.dismiss_fn = lambda item_id: {"ok": True}
    assert client(ctx).post("/api/dismiss", json={"item_id": "../x"}).status_code == 422


LAN = ("192.168.1.50", 50000)


def lan_client(ctx):
    return TestClient(create_app(ctx), client=LAN)


@pytest.mark.parametrize("path", ["/stream", "/dashboard", "/health.html"])
def test_lan_denied_pages(ctx, path):
    assert lan_client(ctx).get(path).status_code == 403


@pytest.mark.parametrize("path,body", [
    ("/api/ask", {"question": "x"}),
    ("/api/enroll", {"item_id": "a", "display_name": "A"}),
    ("/api/enroll/click", {"item_id": "a", "display_name": "A", "x": 1, "y": 2}),
    ("/api/forget", {"item_id": "a"}),
])
def test_lan_denied_posts(ctx, path, body):
    calls = []
    ctx.ask_fn = lambda q, s: calls.append(q) or {}
    ctx.enroll_fn = lambda **kw: calls.append(kw) or {}
    ctx.forget_fn = lambda i: calls.append(i) or {}
    assert lan_client(ctx).post(path, json=body).status_code == 403
    assert calls == []


def test_lan_allowed_paths(ctx, tmp_path):
    c = lan_client(ctx)
    (tmp_path / "clips" / "a.txt").write_text("hi")
    for path in ("/frame", "/manifest.json", "/health", "/clips/a.txt"):
        assert c.get(path).status_code == 200, path
    with c.websocket_connect("/ws") as ws:
        ctx.bus.publish("show_answer", answer={"text": "hi"})
        assert ws.receive_json()["type"] == "show_answer"


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost"])
def test_loopback_allowed(ctx, host):
    c = TestClient(create_app(ctx), client=(host, 50000))
    assert c.get("/dashboard").status_code == 200
    assert c.post("/api/ask", json={"question": "x"}).status_code == 503  # past the guard


def test_lan_dashboard_flag_opens_lan(ctx):
    ctx.cfg.server.lan_dashboard = True
    ctx.ask_fn = lambda q, s: {"text": "ok"}
    c = lan_client(ctx)
    assert c.get("/dashboard").status_code == 200
    assert c.post("/api/ask", json={"question": "x"}).json() == {"text": "ok"}


@pytest.mark.parametrize("bad", ["../x", "", "a/b", "A", "x" * 41])
def test_item_id_validated(ctx, bad):
    ctx.enroll_fn = lambda **kw: {}
    ctx.forget_fn = lambda i: {}
    c = client(ctx)
    assert c.post("/api/enroll", json={"item_id": bad, "display_name": "A"}).status_code == 422
    assert c.post("/api/enroll/click", json={"item_id": bad, "display_name": "A",
                                             "x": 1, "y": 2}).status_code == 422
    assert c.post("/api/forget", json={"item_id": bad}).status_code == 422


class FakeVoiceSettings:
    def __init__(self):
        self.voice, self.tested = "mac", 0

    def state(self):
        return {"voice": self.voice, "voices": [{"id": "mac", "label": "Mac", "disabled": False},
                                                {"id": "grok:eve", "label": "Grok · Eve", "disabled": False}],
                "grok": True}

    def set_voice(self, v):
        if v not in ("mac", "grok:eve"):
            return False
        self.voice = v
        return True

    def test(self):
        self.tested += 1


def test_settings_get_and_set(ctx):
    ctx.voice_settings = FakeVoiceSettings()
    c = client(ctx)
    assert c.get("/api/settings").json()["voice"] == "mac"
    r = c.post("/api/settings", json={"voice": "grok:eve"})
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["voice"] == "grok:eve"
    r = c.post("/api/settings", json={"voice": "grok:nobody"})
    assert r.json()["ok"] is False and r.json()["voice"] == "grok:eve"


def test_settings_test_voice(ctx):
    ctx.voice_settings = vs = FakeVoiceSettings()
    assert client(ctx).post("/api/settings/test_voice", json={}).json() == {"ok": True}
    assert vs.tested == 1


def test_settings_unavailable_without_voice(ctx):
    c = client(ctx)
    assert c.get("/api/settings").status_code == 503
    assert c.post("/api/settings", json={"voice": "mac"}).status_code == 503
