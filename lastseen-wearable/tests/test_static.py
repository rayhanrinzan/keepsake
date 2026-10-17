from tests.test_server import client, ctx  # noqa: F401  (fixture reuse)


def test_frame_page_has_ws_and_video(ctx):
    r = client(ctx).get("/frame")
    assert r.status_code == 200
    for needle in ("new WebSocket", "playsinline", "show_answer", "manifest.json", "display_name"):
        assert needle in r.text


def test_manifest(ctx):
    r = client(ctx).get("/manifest.json")
    assert r.status_code == 200
    j = r.json()
    assert j["name"] == "Last Seen" and j["display"] == "fullscreen"


def test_dashboard_page(ctx):
    r = client(ctx).get("/dashboard")
    assert r.status_code == 200
    for needle in ("/stream", "new WebSocket", "/api/ask", "/api/items", "/api/events",
                   "/api/enroll/click", "Backup controls", "textContent"):
        assert needle in r.text
    assert "innerHTML" not in r.text


def test_api_items(ctx):
    ctx.store.upsert_item("airpods", "AirPods", False, "PLACED", "desk", (1, 2, 3, 4), 0.9, 5.0)
    j = client(ctx).get("/api/items").json()
    assert [i["id"] for i in j] == ["airpods"] and j[0]["state"] == "PLACED"


def test_api_events_order_and_clamp(ctx):
    from lastseen.types import TrackerEvent
    for i in range(5):
        ctx.store.add_event(TrackerEvent("PLACED", "a", float(i), None, "z", None, 0.9))
    c = client(ctx)
    j = c.get("/api/events?n=2").json()
    assert len(j) == 2 and j[0]["ts"] == 4.0 and j[1]["ts"] == 3.0
    assert len(c.get("/api/events").json()) == 5
    assert len(c.get("/api/events?n=0").json()) == 1
    assert len(c.get("/api/events?n=-5").json()) == 1
    assert len(c.get("/api/events?n=9999").json()) == 5


def test_dashboard_wearable_view(ctx):
    r = client(ctx).get("/dashboard")
    for needle in ("wear_status", "/api/dismiss", "I know where it is", 'id="camlost"', 'id="bigsnap"'):
        assert needle in r.text
    assert "innerHTML" not in r.text


def test_dashboard_hides_stale_rows_in_wearable(ctx):
    html = client(ctx).get("/dashboard").text
    assert "config_ids" in html            # wear_status carries the config item ids
    assert "function visibleIds" in html   # rows outside wear_status/config are hidden
    assert 'w.phase==="UNTRACKED")?null' in html   # no old-session thumbnail on an untouched card
