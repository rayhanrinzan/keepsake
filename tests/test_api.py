"""API round-trips with the camera disabled; sightings are injected synthetically."""
import importlib

import pytest
from fastapi.testclient import TestClient

from catalog import CATALOG
from conftest import BED, DESK, Pipeline, obs


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("CTRLF_CAMERA_ENABLED", "0")
    monkeypatch.setenv("CTRLF_REMINDERS_THREAD", "0")
    monkeypatch.setenv("CTRLF_DB_PATH", str(tmp_path / "api.db"))
    monkeypatch.setenv("CTRLF_SNAPSHOT_DIR", str(tmp_path / "snaps"))
    monkeypatch.setenv("CTRLF_ENV_FILE", str(tmp_path / "missing.env"))  # never read the real key
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    import main
    main = importlib.reload(main)
    with TestClient(main.app) as c:
        yield c, main


def see(main, *observations, n=6, pipe=None):
    """Synthetic frames through the live worker's path (memory, observer, photo)."""
    pipe = pipe or Pipeline(main.memory, main.snapshots)
    pipe.frames(n, *observations)
    return pipe


def test_catalog_and_never_seen_objects(api):
    c, _ = api
    objs = c.get("/api/objects").json()
    assert [o["name"] for o in objs][:2] == ["Water Bottle", "Keys"] and len(objs) == len(CATALOG)
    assert all(o["status"] == "never" and o["snapshot"] is None for o in objs)
    assert all("region" not in o and "x" not in o for o in objs)  # no room positions, ever
    assert len(c.get("/api/catalog").json()) == len(CATALOG)
    health = c.get("/api/health").json()
    assert health["camera"] == "disabled" and health["camera_mode"] == "wearable"


def test_object_photo_and_query_flow(api):
    c, main = api
    pipe = see(main, obs("bottle", DESK))
    assert c.get("/api/objects/wallet").json()["status"] == "never"
    bottle = c.get("/api/objects/bottle_01").json()
    assert bottle["status"] == "visible" and bottle["seen"]
    snap = bottle["snapshot"]
    assert snap["event_type"] == "object_observed" and len(snap["bbox"]) == 4 and "region" not in snap
    img = c.get(snap["image_url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
    assert c.get("/api/snapshots/9999/image").status_code == 404

    pipe.frames(15)  # out of view
    r = c.post("/api/query", json={"text": "My water bottle"}).json()
    assert r["found"] and r["object"]["snapshot"]["id"] == snap["id"]
    assert r["object"]["status"] == "last_seen" and "The last photo is in Keepsake." in r["answer"]
    assert "may have moved" in r["answer"]
    bad = c.post("/api/query", json={"text": "where is my umbrella"}).json()
    assert bad["found"] is False and bad["object"] is None
    assert c.get("/api/objects/bottle_01/snapshots").json()[0]["id"] == snap["id"]
    activity = c.get("/api/events").json()
    assert activity[0]["event_type"] == "object_observed" and activity[0]["name"] == "Water Bottle"


def test_list_and_detail_share_one_object_state(api):
    c, main = api
    see(main, obs("backpack", BED))
    listing = {o["object_id"]: o for o in c.get("/api/objects").json()}
    assert listing["backpack_01"] == c.get("/api/objects/backpack_01").json()


def test_settings_toggle_capture(api):
    c, main = api
    assert c.put("/api/settings", json={"capture_enabled": False}).json() == {"capture_enabled": False}
    see(main, obs("backpack", DESK))
    bag = c.get("/api/objects/backpack_01").json()
    assert bag["seen"] and bag["snapshot"] is None
    assert c.get("/api/health").json()["capture_enabled"] is False


def test_clear_memory_removes_photos(api):
    c, main = api
    see(main, obs("bottle", DESK))
    assert list(main.snapshots.dir.glob("*.jpg"))
    assert c.delete("/api/memory").json() == {"cleared": True}
    assert all(o["status"] == "never" for o in c.get("/api/objects").json())
    assert list(main.snapshots.dir.glob("*.jpg")) == [] and c.get("/api/events").json() == []


def test_room_area_and_scan_endpoints_are_gone(api):
    c, _ = api
    for method, path in [("get", "/api/regions"), ("put", "/api/regions"), ("post", "/api/reposition/start"),
                         ("get", "/api/calibration/reference"), ("get", "/api/departures")]:
        assert getattr(c, method)(path).status_code in (404, 405), path
