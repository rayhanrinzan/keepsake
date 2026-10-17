"""API round-trips with the camera disabled; observations are injected synthetically."""
import importlib

import numpy as np
import pytest
from fastapi.testclient import TestClient

from conftest import BED, DESK, TEST_AREAS, Clock, obs
from catalog import CATALOG
from spatial import save_regions


@pytest.fixture
def api(tmp_path, monkeypatch):
    save_regions(TEST_AREAS, tmp_path / "regions.json")
    monkeypatch.setenv("CTRLF_CAMERA_ENABLED", "0")
    monkeypatch.setenv("CTRLF_DB_PATH", str(tmp_path / "api.db"))
    monkeypatch.setenv("CTRLF_SNAPSHOT_DIR", str(tmp_path / "snaps"))
    monkeypatch.setenv("CTRLF_REGIONS", str(tmp_path / "regions.json"))
    import main
    main = importlib.reload(main)
    with TestClient(main.app) as c:
        yield c, main


def inject(main, *observations, n=6, clock=None):
    """Synthetic detections through the same path the live worker uses (memory -> snapshots)."""
    clock = clock or Clock(main.memory)
    frame = np.full((360, 640, 3), 100, np.uint8)
    for ev in clock.frames(n, *observations):
        main.snapshots.submit(ev, frame)
    main.snapshots.flush()
    return clock


def test_catalog_and_never_seen_objects(api):
    c, _ = api
    objs = c.get("/api/objects").json()
    assert [o["name"] for o in objs][:2] == ["Water Bottle", "Keys"] and len(objs) == len(CATALOG)
    assert all(o["status"] == "never" and o["region"] is None and o["snapshot"] is None for o in objs)
    assert len(c.get("/api/catalog").json()) == len(CATALOG)
    assert c.get("/api/health").json()["camera"] == "disabled"


def test_object_snapshot_and_query_flow(api):
    c, main = api
    clock = inject(main, obs("bottle", DESK))
    wallet = c.get("/api/objects/wallet").json()
    assert wallet["status"] == "never"
    bottle = c.get("/api/objects/bottle_01").json()
    assert bottle["status"] == "visible" and bottle["region"] == "Desk"
    snap = bottle["snapshot"]
    assert snap["event_type"] == "first_seen" and len(snap["bbox"]) == 4
    img = c.get(snap["image_url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
    assert c.get("/api/snapshots/9999/image").status_code == 404

    clock.frames(15)  # leaves view
    r = c.post("/api/query", json={"text": "My water bottle"}).json()
    assert r["found"] and r["object"]["snapshot"]["id"] == snap["id"]
    assert r["object"]["status"] == "last_seen" and "out of view" in r["answer"]
    bad = c.post("/api/query", json={"text": "where is my umbrella"}).json()
    assert bad["found"] is False and bad["object"] is None
    assert c.get("/api/objects/bottle_01/snapshots").json()[0]["id"] == snap["id"]
    assert c.get("/api/events").json()[0]["event_type"] == "first_seen"


def test_list_and_map_share_one_object_state(api):
    c, main = api
    inject(main, obs("backpack", BED))
    listing = {o["object_id"]: o for o in c.get("/api/objects").json()}
    detail = c.get("/api/objects/backpack_01").json()
    assert listing["backpack_01"] == detail  # both views render this exact record


def test_settings_toggle_capture(api):
    c, main = api
    assert c.put("/api/settings", json={"capture_enabled": False}).json() == {"capture_enabled": False}
    inject(main, obs("backpack", DESK))
    bag = c.get("/api/objects/backpack_01").json()
    assert bag["region"] == "Desk" and bag["snapshot"] is None
    assert c.get("/api/health").json()["capture_enabled"] is False


def test_clear_memory_removes_photos(api):
    c, main = api
    inject(main, obs("bottle", DESK))
    assert list(main.snapshots.dir.glob("*.jpg"))
    assert c.delete("/api/memory").json() == {"cleared": True}
    assert all(o["status"] == "never" for o in c.get("/api/objects").json())
    assert list(main.snapshots.dir.glob("*.jpg")) == []


def test_reposition_flow_preserves_history(api):
    c, main = api
    clock = inject(main, obs("bottle", DESK))
    old_snap = c.get("/api/objects/bottle_01").json()["snapshot"]

    assert c.post("/api/reposition/start").json()["mode"] == "REPOSITIONING"
    assert c.post("/api/reposition/start").status_code == 409
    inject(main, obs("bottle", BED), n=20, clock=clock)  # camera swinging around
    assert len(c.get("/api/events").json()) == 1
    assert c.get("/api/objects/bottle_01/snapshots").json() == [old_snap]

    assert c.post("/api/reposition/finish").json()["mode"] == "CALIBRATING"
    assert c.get("/api/calibration/reference").status_code == 404
    scan = lambda: (b"jpeg", [{"name": "Couch", "kind": "couch", "camera": [0, 0, 0.5, 1]}])  # noqa: E731
    for _ in range(6):
        main.modes.on_frame(0.0, scan)  # worker sees a steady view, then scans it
    assert c.get("/api/calibration/reference").content == b"jpeg"
    assert c.get("/api/health").json()["proposal"][0]["name"] == "Couch"

    new = [{"name": "Desk", "camera": [0.5, 0, 1, 1]},
           {"name": "Couch", "kind": "couch", "camera": [0, 0, 0.5, 1]}]
    assert c.put("/api/regions", json={"regions": [{"name": "X", "camera": [0.5, 0, 0.4, 1]}]}).status_code == 422
    assert c.put("/api/regions", json={"regions": [{"name": "Near Bed", "camera": [0, 0, 1, 1]}]}).status_code == 422
    assert [r["name"] for r in c.put("/api/regions", json={"regions": new}).json()] == ["Desk", "Couch"]
    assert c.get("/api/health").json()["mode"] == "READY_TO_RESUME"
    assert c.post("/api/reposition/resume").json()["mode"] == "MONITORING"

    bottle = c.get("/api/objects/bottle_01").json()
    assert bottle["awaiting_reconfirmation"] and bottle["snapshot"]["id"] == old_snap["id"]
    inject(main, obs("bottle", (0.8, 0.5)), clock=clock)  # now inside the recalibrated Desk
    bottle = c.get("/api/objects/bottle_01").json()
    assert bottle["region"] == "Desk" and not bottle["awaiting_reconfirmation"]
    assert bottle["snapshot"]["event_type"] == "reconfirmed"
    assert [e["event_type"] for e in c.get("/api/events").json()] == ["first_seen"]
    assert len(c.get("/api/objects/bottle_01/snapshots").json()) == 2  # old photo kept


def test_cancel_reposition(api):
    c, main = api
    view = main.memory.view_id
    c.post("/api/reposition/start")
    assert c.post("/api/reposition/resume").status_code == 409
    assert c.post("/api/reposition/cancel").json()["mode"] == "MONITORING"
    assert main.memory.view_id == view and not main.memory.paused


def test_cancel_from_any_scan_step_keeps_old_areas(api):
    c, main = api
    before = c.get("/api/regions").json()
    view = main.memory.view_id
    c.post("/api/reposition/start")
    c.post("/api/reposition/finish")
    for _ in range(6):  # scan completes, waiting on review
        main.modes.on_frame(0.0, lambda: (b"jpeg", []))
    assert c.post("/api/reposition/cancel").json()["mode"] == "MONITORING"
    assert c.get("/api/regions").json() == before and main.memory.view_id == view

    c.post("/api/reposition/start")
    c.post("/api/reposition/finish")
    for _ in range(6):
        main.modes.on_frame(0.0, lambda: (b"jpeg", []))
    c.put("/api/regions", json={"regions": [{"name": "Shelf", "camera": [0, 0, 0.5, 0.5]}]})
    assert c.post("/api/reposition/cancel").json()["mode"] == "MONITORING"
    assert c.get("/api/regions").json() == before  # saved-but-not-resumed areas rolled back
    assert c.post("/api/reposition/cancel").status_code == 409
