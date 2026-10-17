"""Keepsake API server. Run: python main.py (binds to 127.0.0.1 only)."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel

from catalog import CATALOG
from database import Database
from departure import DepartureDetector
from departure_api import departure_router
from memory import SpatialMemory, answer_query, parse_query
from modes import ModeController, ModeError
from snapshots import SnapshotStore
from spatial import load_regions, save_regions, validate_regions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
HERE = Path(__file__).parent


def env(name: str, default: str) -> str:
    return os.getenv(f"CTRLF_{name}", default)


# Our own trained model (last-seen/train.py) if it's installed, otherwise YOLO-World as a fallback.
_ITEMS_MODEL = HERE / "models" / "items.pt"
DEFAULT_MODEL = str(_ITEMS_MODEL if _ITEMS_MODEL.exists() else HERE / "models" / "yolov8s-worldv2.pt")
DEFAULT_CONF = "0.35" if _ITEMS_MODEL.exists() else "0.15"

regions = load_regions()
db = Database(env("DB_PATH", str(HERE / "data" / "ctrlf.db")))
memory = SpatialMemory(db, regions, stability=int(env("STABILITY_FRAMES", "4")),
                       min_confidence=float(env("CONFIDENCE", "0.35")),  # fallback; per-item min_conf in catalog.py
                       absence_seconds=float(env("ABSENCE_SECONDS", "2.0")),
                       move_threshold=float(env("MOVE_THRESHOLD", "0.06")),
                       settle_seconds=float(env("SETTLE_SECONDS", "0.8")))
snapshots = SnapshotStore(db, env("SNAPSHOT_DIR", str(HERE / "data" / "snapshots")),
                          retention=int(env("SNAPSHOT_RETENTION", "20")),
                          cooldown_seconds=float(env("SNAPSHOT_COOLDOWN", "3")))
modes = ModeController(memory)
departures = DepartureDetector(db)  # possible departures for Departure Alerts (integrations/photon)
_regions_before: list = []  # areas when the current scan started
worker = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global worker
    if env("CAMERA_ENABLED", "1") == "1":
        from vision import VisionWorker  # imported lazily so tests don't need a camera stack
        source = env("CAMERA_INDEX", "0")  # webcam index, or a video file path for testing
        worker = VisionWorker(memory, regions, snapshots, modes,
                              camera_index=int(source) if source.isdigit() else source,
                              model_path=env("MODEL", DEFAULT_MODEL),
                              # candidate cutoff; each item then needs its own min_conf (catalog.py)
                              conf=float(env("DETECT_CONFIDENCE", DEFAULT_CONF)),
                              fps=float(env("INFERENCE_FPS", "5")),
                              scan_model_path=env("SCAN_MODEL", str(HERE / "models" / ("yolo11m.pt" if (HERE / "models" / "yolo11m.pt").exists() else "yolo11n.pt"))),
                              frame_width=int(env("INFERENCE_WIDTH", "1280")),
                              device=env("DEVICE", "") or None, departures=departures)
        worker.start()
    yield
    if worker:
        worker.stop()
        worker.join(timeout=5)
    snapshots.flush()
    db.close()


app = FastAPI(title="Keepsake", lifespan=lifespan)
app.add_middleware(CORSMiddleware,
                   allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(departure_router(departures, db, memory, modes, regions, lambda: worker))


# ---------- serializers ----------

def snapshot_view(s: dict | None) -> dict | None:
    if not s:
        return None
    return {"id": s["id"], "object_id": s["object_id"], "event_type": s["event_type"],
            "timestamp": s["timestamp"], "region": s["region"],
            "bbox": [s["x0"], s["y0"], s["x1"], s["y1"]], "confidence": s["confidence"],
            "view_id": s["view_id"], "image_url": f"/api/snapshots/{s['id']}/image"}


def object_view(item: dict, rec: dict | None, snap: dict | None, states: dict) -> dict:
    """The one canonical object shape used by List, Map, detail and voice."""
    base = {"object_id": item["object_id"], "category": item["category"], "name": item["name"],
            "icon": item["icon"], "seen": rec is not None and rec.get("region") is not None}
    if not base["seen"]:
        return {**base, "status": "never", "region": None, "x": None, "y": None,
                "last_seen": None, "visible": False, "confidence": None, "moving": False,
                "awaiting_reconfirmation": False, "lost_while_moving": False, "snapshot": None}
    awaiting = rec.get("view_id") not in (None, memory.view_id)
    return {**base, "status": "visible" if rec["visible"] else "last_seen",
            "region": rec["region"], "x": rec["x"], "y": rec["y"], "last_seen": rec["last_seen"],
            "visible": rec["visible"], "confidence": rec["confidence"],
            "moving": states.get(item["category"], "STABLE") != "STABLE",
            "awaiting_reconfirmation": awaiting, "lost_while_moving": rec["lost_while_moving"],
            "snapshot": snapshot_view(snap)}


def all_objects() -> list[dict]:
    recs = {r["category"]: r for r in db.get_objects()}
    latest = db.latest_snapshots()
    states = memory.states()
    return [object_view(c, recs.get(c["category"]), latest.get(c["object_id"]), states)
            for c in CATALOG]


def find_item(object_id: str) -> dict | None:
    for c in CATALOG:
        if c["object_id"] == object_id:
            return c
    parsed = parse_query(object_id.replace("_", " "))  # also accept a name/alias, e.g. "phone"
    return next((c for c in CATALOG if parsed and c["category"] == parsed[0]), None)


# ---------- read endpoints ----------

@app.get("/api/health")
def health():
    status = dict(worker.status) if worker else {"camera": "disabled", "error": None,
                                                 "warning": None, "fps": 0, "detections": []}
    return {"status": "ok", **status, **modes.status(), "capture_enabled": snapshots.enabled}


@app.get("/api/catalog")
def get_catalog():
    return [{k: c[k] for k in ("object_id", "category", "name", "icon", "aliases")} for c in CATALOG]


@app.get("/api/regions")
def get_regions():
    return [r.to_dict() for r in regions]


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
    return [snapshot_view(s) for s in db.get_snapshots(item["object_id"], min(limit, 100))]


@app.get("/api/snapshots/{snapshot_id}/image")
def get_snapshot_image(snapshot_id: int):
    s = db.get_snapshot(snapshot_id)
    path = snapshots.path_for(s["filename"]) if s else None
    if path is None:
        raise HTTPException(404, "Photo not found")
    return FileResponse(path, media_type="image/jpeg",
                        headers={"Cache-Control": "private, max-age=31536000, immutable"})


@app.get("/api/events")
def get_events(limit: int = 50):
    names = {c["object_id"]: c["name"] for c in CATALOG}
    return [{**e, "name": names.get(e["object_id"], e["name"])} for e in db.get_events(limit)]


class Query(BaseModel):
    text: str


@app.post("/api/query")
def query(q: Query):
    r = answer_query(q.text, db, view_id=memory.view_id, regions=regions)
    obj = None
    if r["category"]:
        obj = next(o for o in all_objects() if o["category"] == r["category"])
    return {"found": r["found"], "answer": r["answer"], "object": obj}


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


@app.delete("/api/memory")
def clear_memory():
    """Forget every object location, movement event and stored photo."""
    memory.reset()
    snapshots.clear()
    return {"cleared": True}


# ---------- Scan room (reposition + calibration) ----------

def _mode_call(fn):
    try:
        fn()
    except ModeError as e:
        raise HTTPException(409, str(e)) from e
    return modes.status()


@app.post("/api/reposition/start")
def reposition_start():
    status = _mode_call(modes.start)
    _regions_before[:] = list(regions)  # restored if the scan is cancelled after saving
    return status


@app.post("/api/reposition/cancel")
def reposition_cancel():
    """Leave Scan room from any step; the room areas go back to what they were before it."""
    try:
        areas_changed = modes.cancel()
    except ModeError as e:
        raise HTTPException(409, str(e)) from e
    if areas_changed:
        regions[:] = _regions_before
        if env("REGIONS_READONLY", "0") != "1":
            save_regions(regions)
    return modes.status()


@app.post("/api/reposition/finish")
def reposition_finish():
    return _mode_call(modes.finish)


@app.post("/api/reposition/resume")
def reposition_resume():
    return _mode_call(modes.resume)


@app.get("/api/calibration/reference")
def calibration_reference():
    if modes.reference_jpeg is None:
        raise HTTPException(404, "No reference frame yet")
    return Response(modes.reference_jpeg, media_type="image/jpeg",
                    headers={"Cache-Control": "no-store"})


class RegionIn(BaseModel):
    name: str
    camera: list[float]
    kind: str = "custom"


class RegionsIn(BaseModel):
    regions: list[RegionIn]


@app.put("/api/regions")
def put_regions(body: RegionsIn):
    try:
        new = validate_regions([r.model_dump() for r in body.regions])
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(422, str(e)) from e
    regions[:] = new  # shared with SpatialMemory and the vision worker
    if env("REGIONS_READONLY", "0") != "1":
        save_regions(regions)
    modes.regions_saved()
    return [r.to_dict() for r in regions]


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
