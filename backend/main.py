"""Keepsake API server. Run: python main.py (binds to 127.0.0.1 only)."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from contextlib import asynccontextmanager
from pathlib import Path

import cv2
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from typing import Literal

from pydantic import BaseModel, Field

import events as observation_events
from catalog import CATALOG
from database import Database
from reminders import ReminderEngine
from reminders_api import reminders_router
from memory import ItemMemory, answer_query, parse_query
from snapshots import SnapshotStore
from describe import SceneDescriber
from voice import SPEED_RANGE, GrokTTS, TTSError, load_env_file

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
HERE = Path(__file__).parent


def env(name: str, default: str) -> str:
    return os.getenv(f"CTRLF_{name}", default)


load_env_file(env("ENV_FILE", str(HERE.parent / ".env")))  # e.g. XAI_API_KEY for the Grok voice

# YOLO-World finds everything; vision.py adds models/items.pt (our trained items) on top if present.
DEFAULT_MODEL = str(HERE / "models" / "yolov8s-worldv2.pt")
DEFAULT_CONF = "0.15"  # candidate cutoff; each item then needs its own min_conf (catalog.py)
# Keepsake is wearable-only: a chest-mounted phone, so there are no room areas or screen positions.
db = Database(env("DB_PATH", str(HERE / "data" / "ctrlf.db")))
memory = ItemMemory(db, stability=int(env("STABILITY_FRAMES", "3")),
                    min_confidence=float(env("CONFIDENCE", "0.35")),  # fallback; per-item min_conf in catalog.py
                    absence_seconds=float(env("ABSENCE_SECONDS", "2.0")),
                    settle_seconds=float(env("SETTLE_SECONDS", "1.0")))
snapshots = SnapshotStore(db, env("SNAPSHOT_DIR", str(HERE / "data" / "snapshots")),
                          retention=int(env("SNAPSHOT_RETENTION", "20")),
                          cooldown_seconds=float(env("SNAPSHOT_COOLDOWN", "3")))
reminders = ReminderEngine(db, memory, status_fn=lambda: dict(worker.status) if worker else {},
                           photo_available=lambda photo: snapshots.path_for(photo["filename"]) is not None)
worker = None
grok = GrokTTS(os.environ["XAI_API_KEY"]) if os.getenv("XAI_API_KEY") else None
describer = SceneDescriber()  # Grok vision: "on a green seat next to…" (CTRLF_DESCRIBE=0 turns it off)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global worker
    if env("CAMERA_ENABLED", "1") == "1":
        from vision import VisionWorker  # imported lazily so tests don't need a camera stack
        source = env("CAMERA_INDEX", "0")  # webcam index, or a video file path for testing
        worker = VisionWorker(memory, snapshots,
                              camera_index=int(source) if source.isdigit() else source,
                              camera_name=env("CAMERA_NAME", "") or None,  # e.g. iPhone; wins over the index
                              model_path=env("MODEL", DEFAULT_MODEL),
                              # candidate cutoff; each item then needs its own min_conf (catalog.py)
                              conf=float(env("DETECT_CONFIDENCE", DEFAULT_CONF)),
                              fps=float(env("INFERENCE_FPS", "5")),
                              frame_width=int(env("INFERENCE_WIDTH", "1280")),
                              device=env("DEVICE", "") or None,
                              hands_enabled=env("HANDS", "1") == "1",
                              verify_enabled=env("VERIFY", "1") == "1")  # CLIP second opinion
        worker.start()
    if env("REMINDERS_THREAD", "1") == "1":
        reminders.start()  # its own thread: never blocks the camera loop
    yield
    reminders.stop()
    if worker:
        worker.stop()
        worker.join(timeout=5)
    snapshots.flush()
    db.close()


app = FastAPI(title="Keepsake", lifespan=lifespan)
# Pages on this machine only: the web app (5173) and the mobile app's web build (Expo, 8081 or any
# other local port). The backend itself binds 127.0.0.1.
app.add_middleware(CORSMiddleware,
                   allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(reminders_router(reminders))


# ---------- serializers ----------

def snapshot_view(s: dict | None) -> dict | None:
    if not s or snapshots.path_for(s["filename"]) is None:
        return None
    return {"id": s["id"], "object_id": s["object_id"], "event_type": s["event_type"],
            "timestamp": s["timestamp"], "bbox": [s["x0"], s["y0"], s["x1"], s["y1"]],
            "confidence": s["confidence"], "image_url": f"/api/snapshots/{s['id']}/image"}


def _when(row: dict) -> float:
    return datetime.fromisoformat(row["timestamp"]).timestamp()


def object_view(item: dict, rec: dict | None, snap: dict | None) -> dict:
    """The one canonical object shape used by List, detail, voice and Photon.

    Grounded only in what a worn camera proves: the last real sighting (memory or a vision
    observation, whichever is newer), whether it's in view now, and its newest photo. No room area
    or screen position: where the wearer happened to look isn't where the item is."""
    if snap and snapshots.path_for(snap["filename"]) is None:
        snap = None
    observation = db.latest_sighting(item["object_id"])
    if observation and observation["snapshot_id"] is not None:
        photo = db.get_snapshot(observation["snapshot_id"])
        if (photo and photo["object_id"] == item["object_id"] and snapshots.path_for(photo["filename"])
                and (snap is None or _when(photo) >= _when(snap))):
            snap = photo  # the observation's own photo, unless a newer sighting photo exists
    last_seen, visible, confidence = None, False, None
    if rec is not None:
        last_seen, visible, confidence = rec["last_seen"], bool(rec["visible"]), rec["confidence"]
    if observation and (last_seen is None or datetime.fromisoformat(observation["timestamp"]).timestamp()
                        > datetime.fromisoformat(last_seen).timestamp()):
        last_seen, confidence = observation["timestamp"], observation["confidence"]
    if last_seen is None and snap:
        last_seen, confidence = snap["timestamp"], snap["confidence"]
    base = {"object_id": item["object_id"], "category": item["category"], "name": item["name"],
            "icon": item["icon"], "seen": last_seen is not None}
    if not base["seen"]:
        return {**base, "status": "never", "last_seen": None, "visible": False, "confidence": None,
                "snapshot": None}
    return {**base, "status": "visible" if visible else "last_seen", "last_seen": last_seen,
            "visible": visible, "confidence": confidence, "snapshot": snapshot_view(snap)}


def all_objects() -> list[dict]:
    recs = {r["category"]: r for r in db.get_objects()}
    latest = db.latest_snapshots()
    return [object_view(c, recs.get(c["category"]), latest.get(c["object_id"])) for c in CATALOG]


def find_item(object_id: str) -> dict | None:
    for c in CATALOG:
        if c["object_id"] == object_id:
            return c
    parsed = parse_query(object_id.replace("_", " "))  # also accept a name/alias, e.g. "keys"
    return next((c for c in CATALOG if parsed and c["category"] == parsed[0]), None)


# ---------- read endpoints ----------

@app.get("/api/health")
def health():
    status = dict(worker.status) if worker else {"camera": "disabled", "error": None,
                                                 "warning": None, "fps": 0, "detections": [],
                                                 "camera_mode": "wearable"}
    status["person_left_count"] = 0  # other people leaving a worn camera is not the wearer leaving
    return {"status": "ok", **status, "capture_enabled": snapshots.enabled}


@app.get("/api/catalog")
def get_catalog():
    return [{k: c[k] for k in ("object_id", "category", "name", "icon", "aliases")} for c in CATALOG]


@app.get("/api/objects")
def get_objects():
    return all_objects()


@app.get("/api/objects/{object_id}")
def get_object(object_id: str):
    item = find_item(object_id)
    if item is None:
        raise HTTPException(404, "Keepsake doesn't track that item")
    return next(o for o in all_objects() if o["object_id"] == item["object_id"])


@app.get("/api/objects/{object_id}/snapshots")
def get_object_snapshots(object_id: str, limit: int = 20):
    item = find_item(object_id)
    if item is None:
        raise HTTPException(404, "Keepsake doesn't track that item")
    return [view for s in db.get_snapshots(item["object_id"], min(limit, 100))
            if (view := snapshot_view(s)) is not None]


@app.get("/api/snapshots/{snapshot_id}/image")
def get_snapshot_image(snapshot_id: int, highlight: bool = False):
    """The stored photo. `highlight=1` circles the item in white (used for photos sent over Photon)."""
    s = db.get_snapshot(snapshot_id)
    path = snapshots.path_for(s["filename"]) if s else None
    if path is None:
        raise HTTPException(404, "Photo not found")
    if highlight:
        data = snapshots.highlighted(s)
        if data is None:
            raise HTTPException(404, "Photo not found")
        return Response(data, media_type="image/jpeg",
                        headers={"Cache-Control": "private, max-age=31536000, immutable"})
    return FileResponse(path, media_type="image/jpeg",
                        headers={"Cache-Control": "private, max-age=31536000, immutable"})


@app.get("/api/events")
def get_events(limit: int = 50):
    """Recent activity: real observation events (seen, hand near, possible pickup, put down)."""
    names = {c["object_id"]: c["name"] for c in CATALOG}
    return [{"id": e["seq"], "object_id": e["object_id"], "name": names.get(e["object_id"], e["name"]),
             "event_type": e["event_type"], "timestamp": e["timestamp"], "confidence": e["confidence"]}
            for e in db.get_observations(min(max(limit, 1), 200))]


@app.get("/api/observations")
def get_observations(limit: int = 50, after_seq: int = 0, event_type: str | None = None,
                     object_id: str | None = None):
    """Wearable observation events (contract: GET /api/observations/contract), newest first.
    Poll with after_seq = the largest `seq` you've seen to get only new events."""
    if event_type and event_type not in observation_events.EVENT_TYPES:
        raise HTTPException(422, f"event_type must be one of {list(observation_events.EVENT_TYPES)}")
    if object_id:
        item = find_item(object_id)
        if item is None:
            raise HTTPException(404, "Keepsake doesn't track that item")
        object_id = item["object_id"]
    return db.get_observations(min(max(limit, 1), 500), after_seq, event_type, object_id)


@app.get("/api/observations/contract")
def get_observation_contract():
    return observation_events.contract()


class Query(BaseModel):
    text: str


def describe_surroundings(obj: dict, noun: str) -> str | None:
    """One sentence about what's around the item in its newest photo (Grok vision), or None."""
    snap = obj.get("snapshot") or {}
    s = db.get_snapshot(snap["id"]) if snap.get("id") else None
    path = snapshots.path_for(s["filename"]) if s else None
    return describer.describe(snap.get("id"), path, noun, snap.get("bbox"))


@app.post("/api/query")
def query(q: Query):
    r = answer_query(q.text, lambda cat: next(o for o in all_objects() if o["category"] == cat),
                     describe_surroundings)
    return {"found": r["found"], "answer": r["answer"], "object": r["object"], "category": r["category"],
            "surroundings": r.get("surroundings")}

# ---------- settings & privacy ----------

class Settings(BaseModel):
    capture_enabled: bool


@app.get("/api/settings")
def get_settings():
    return {"capture_enabled": snapshots.enabled}


@app.put("/api/settings")
def put_settings(s: Settings):
    snapshots.enabled = s.capture_enabled
    return {"capture_enabled": snapshots.enabled}


# ---------- voice (Grok text to speech) ----------

class VoiceSettings(BaseModel):
    provider: Literal["browser", "grok"]
    voice_id: str = Field(min_length=1, max_length=100)
    speed: float = Field(ge=SPEED_RANGE[0], le=SPEED_RANGE[1])


def voice_settings() -> dict:
    default = "grok" if grok else "browser"
    return {"provider": db.get_setting("voice_provider", default),
            "voice_id": db.get_setting("voice_id", "eve"),
            "speed": float(db.get_setting("voice_speed", "1.0"))}


@app.get("/api/voice")
def get_voice():
    from voice import DEFAULT_VOICES
    return {**voice_settings(), "grok_available": grok is not None,
            "voices": grok.voices() if grok else DEFAULT_VOICES}


@app.put("/api/voice")
def put_voice(v: VoiceSettings):
    db.set_setting("voice_provider", v.provider)
    db.set_setting("voice_id", v.voice_id)
    db.set_setting("voice_speed", str(v.speed))
    return get_voice()


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000, pattern=r"\S")
    voice_id: str | None = Field(default=None, min_length=1, max_length=100)  # Settings preview
    speed: float | None = Field(default=None, ge=SPEED_RANGE[0], le=SPEED_RANGE[1])


@app.post("/api/tts")
def tts(body: SpeakIn):
    """Speak one sentence in the Grok voice. Only this text is sent to xAI."""
    if grok is None:
        raise HTTPException(503, "No Grok key. Add XAI_API_KEY to .env and restart the backend.")
    s = voice_settings()
    try:
        audio = grok.synthesize(body.text.strip(), body.voice_id or s["voice_id"],
                                body.speed if body.speed is not None else s["speed"])
    except TTSError as e:
        raise HTTPException(502, str(e)) from e
    return Response(audio, media_type="audio/mpeg")


@app.delete("/api/memory")
def clear_memory():
    """Forget every sighting, observation event and stored photo."""
    memory.reset()
    snapshots.clear()
    if worker:
        worker.observer.reset()
        worker.interactions.reset()
    return {"cleared": True}


# ---------- live camera ----------

@app.get("/api/camera/frame")
def camera_frame():
    """Newest annotated frame as a single JPEG (kept in memory only). The dashboard polls this;
    short requests recover on their own where a long-lived MJPEG stream can stall in the browser."""
    if worker is None:
        raise HTTPException(503, "Camera disabled")
    frame_id, jpg = worker.latest_frame()
    if jpg is None:
        raise HTTPException(503, "No frame yet")
    return Response(jpg, media_type="image/jpeg",
                    headers={"Cache-Control": "no-store", "X-Frame-Id": str(frame_id)})


@app.get("/api/camera/raw")
def camera_raw():
    """Newest frame without boxes, as JPEG (kept in memory only). For collecting training photos."""
    frame = worker.latest_raw() if worker else None
    if frame is None:
        raise HTTPException(503, "No frame yet")
    ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise HTTPException(500, "Could not encode frame")
    return Response(jpg.tobytes(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/camera")
async def camera():
    """MJPEG stream of the annotated live frame (kept in memory only)."""
    if worker is None:
        raise HTTPException(503, "Camera disabled")

    async def frames():
        last = None
        while True:
            jpg = worker.latest_jpeg()
            if jpg is not None and jpg is not last:
                last = jpg
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"
            await asyncio.sleep(0.05)

    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")


def port_free(host: str, port: int) -> bool:
    import socket
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # as uvicorn does; still fails if listening
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


if __name__ == "__main__":
    import sys

    import uvicorn
    host, port = env("HOST", "127.0.0.1"), int(env("PORT", "8000"))
    # uvicorn starts the camera worker before binding; a second copy must not run the camera at all.
    if not port_free(host, port):
        sys.exit(f"Keepsake is already running on {host}:{port}. Stop it first (Ctrl+C in its window).")
    # The live MJPEG stream never ends on its own; don't let it block shutdown (and keep the camera on).
    uvicorn.run(app, host=host, port=port, timeout_graceful_shutdown=3)
