"""FastAPI server: health, MJPEG stream, websocket bus, clips, API stubs, static pages."""
from __future__ import annotations

import asyncio
import logging
import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

log = logging.getLogger("lastseen.server")
STATIC = Path(__file__).parent / "static"
MAX_STREAM_FPS = 15
LOOPBACK = {"127.0.0.1", "::1", "localhost", "testclient"}
LOCAL_ONLY_PAGES = {"/stream", "/dashboard", "/health.html"}
ItemId = Field(pattern=r"^[a-z0-9_]{1,40}$")  # also a gallery directory name


def default_metrics() -> dict:
    return {k: None for k in ("camera_fps", "camera_ok", "vision_tps", "detector_ms",
                              "clip_ms", "hands_ms", "last_event_ts", "mic", "chalk")}


@dataclass
class AppContext:
    cfg: object
    bus: object
    store: object
    camera: object
    metrics: dict = field(default_factory=default_metrics)
    ask_fn: Callable[[str, str], dict] | None = None
    enroll_fn: Callable[..., dict] | None = None
    overlay_fn: Callable[[np.ndarray], np.ndarray] | None = None
    forget_fn: Callable[[str], dict] | None = None
    dismiss_fn: Callable[[str], dict] | None = None
    voice_settings: object | None = None      # lastseen.voice.settings.VoiceSettings
    stopping: threading.Event = field(default_factory=threading.Event)  # set on Ctrl+C


class AskBody(BaseModel):
    question: str
    source: str = "dashboard"


class EnrollBody(BaseModel):
    item_id: str = ItemId
    display_name: str
    prompt: str | None = None


class ClickBody(BaseModel):
    item_id: str = ItemId
    display_name: str
    x: int
    y: int


class VoiceBody(BaseModel):
    voice: str = Field(max_length=80)


class ForgetBody(BaseModel):
    item_id: str = ItemId


def _placeholder() -> np.ndarray:
    img = np.full((720, 1280, 3), 30, np.uint8)
    cv2.putText(img, "waiting for camera", (360, 370), cv2.FONT_HERSHEY_SIMPLEX, 1.8,
                (200, 200, 200), 3, cv2.LINE_AA)
    return img


def _encode(frame: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buf.tobytes() if ok else b""


def local_only(method: str, path: str) -> bool:
    """Paths only the laptop may use (unless server.lan_dashboard): the wall frame stays open."""
    return path in LOCAL_ONLY_PAGES or (method == "POST" and path.startswith("/api/"))


def create_app(ctx: AppContext) -> FastAPI:
    app = FastAPI(title="Last Seen")

    @app.middleware("http")
    async def lan_guard(request, call_next):
        server_cfg = getattr(ctx.cfg, "server", None)
        if (local_only(request.method, request.url.path)
                and not getattr(server_cfg, "lan_dashboard", False)
                and (request.client is None or request.client.host not in LOOPBACK)):
            return JSONResponse({"detail": "dashboard is local-only (server.lan_dashboard: false)"},
                                status_code=403)
        return await call_next(request)
    clips_dir = Path(ctx.cfg.paths.data) / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    def need(fn, name):
        if fn is None:
            raise HTTPException(503, f"{name} not available yet")
        return fn

    @app.get("/health")
    def health():
        m = {**default_metrics(), **ctx.metrics}
        m["camera_fps"] = getattr(ctx.camera, "fps", None)
        m["camera_ok"] = bool(getattr(ctx.camera, "ok", False))
        return m

    @app.get("/health.html")
    def health_html():
        return FileResponse(STATIC / "health.html")

    @app.get("/frame")
    def frame_page():
        return FileResponse(STATIC / "frame.html")

    @app.get("/manifest.json")
    def manifest():
        return FileResponse(STATIC / "manifest.json", media_type="application/manifest+json")

    @app.get("/dashboard")
    def dashboard_page():
        return FileResponse(STATIC / "dashboard.html")

    @app.get("/stream")
    async def stream():
        placeholder = _encode(_placeholder())

        def make_jpeg() -> bytes:
            frame, _, _ = ctx.camera.get_latest()
            if frame is None:
                return placeholder
            try:
                if ctx.overlay_fn is not None:
                    frame = ctx.overlay_fn(frame)
                return _encode(frame) or placeholder
            except Exception:
                log.exception("overlay/encode failed")
                return placeholder

        async def gen():
            period = 1.0 / MAX_STREAM_FPS
            while not ctx.stopping.is_set():  # ends the response so shutdown is not blocked
                jpg = await asyncio.to_thread(make_jpeg)
                yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                       + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
                await asyncio.sleep(period)

        return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        q = ctx.bus.subscribe()  # before accept: nothing published after connect is lost
        rx = None
        try:
            await sock.accept()

            async def drain():  # notices client disconnects while the bus is idle
                try:
                    while True:
                        await sock.receive()
                except Exception:
                    pass

            rx = asyncio.create_task(drain())
            while not rx.done() and not ctx.stopping.is_set():
                try:
                    msg = await asyncio.to_thread(q.get, True, 0.5)
                except queue.Empty:
                    continue
                await sock.send_json(msg)
        except (WebSocketDisconnect, RuntimeError):
            pass
        except Exception:
            log.exception("ws error")
        finally:
            if rx is not None:
                rx.cancel()
            ctx.bus.unsubscribe(q)

    @app.get("/api/items")
    def api_items():
        return ctx.store.list_items()

    @app.get("/api/events")
    def api_events(n: int = 50):
        return ctx.store.recent_events(max(1, min(200, n)))

    @app.post("/api/ask")
    async def ask(body: AskBody):
        fn = need(ctx.ask_fn, "ask")
        return await asyncio.to_thread(fn, body.question, body.source)

    @app.post("/api/enroll")
    async def enroll(body: EnrollBody):
        fn = need(ctx.enroll_fn, "enroll")
        return await asyncio.to_thread(fn, **body.model_dump())

    @app.post("/api/enroll/click")
    async def enroll_click(body: ClickBody):
        fn = need(ctx.enroll_fn, "enroll")
        return await asyncio.to_thread(fn, **body.model_dump())

    @app.post("/api/forget")
    async def forget(body: ForgetBody):
        fn = need(ctx.forget_fn, "forget")
        return await asyncio.to_thread(fn, body.item_id)

    @app.post("/api/dismiss")
    async def dismiss(body: ForgetBody):
        fn = need(ctx.dismiss_fn, "dismiss")
        return await asyncio.to_thread(fn, body.item_id)

    @app.get("/api/settings")
    def get_settings():
        return need(ctx.voice_settings, "settings").state()

    @app.post("/api/settings")
    def set_settings(body: VoiceBody):
        vs = need(ctx.voice_settings, "settings")
        ok = vs.set_voice(body.voice)
        return {"ok": ok, **vs.state()}

    @app.post("/api/settings/test_voice")
    def test_voice():
        need(ctx.voice_settings, "settings").test()
        return {"ok": True}

    app.mount("/clips", StaticFiles(directory=str(clips_dir)), name="clips")
    return app
