"""Departure Alerts endpoints, polled by the Photon Spectrum agent (integrations/photon).

The backend only reports possible departures and where items were last seen; the agent decides
whether a reminder is warranted and sends it. Keepsake keeps working if the agent is offline.
"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from departure import DepartureFeed, hold_reason
from spatial import place_phrase


def departure_router(feed: DepartureFeed, db, memory, modes, regions, get_worker) -> APIRouter:
    r = APIRouter(prefix="/api/departures")

    def worker_status() -> dict:
        worker = get_worker()
        return dict(worker.status) if worker else {"camera": "disabled"}

    def sync(status: dict) -> str | None:
        hold = hold_reason(modes, memory, status)
        feed.sync(status, hold, memory.view_id)
        return hold

    @r.get("")
    def list_departures(after: int = 0):
        sync(worker_status())
        return {"events": feed.events_after(after), "latest_id": feed.latest_id()}

    @r.get("/context")
    def context():
        """What the alert evaluator needs beyond /api/objects: is the view trustworthy right now,
        and the natural place phrase ("on the couch") for each item's last-seen area."""
        status = worker_status()
        hold = sync(status)
        places = {o["object_id"]: place_phrase(o["region"], regions)
                  for o in db.get_objects() if o.get("region")}
        return {"camera": status.get("camera"), "mode": modes.mode, "view_id": memory.view_id,
                "hold": None if status.get("camera") == "disabled" else hold, "places": places,
                "person_present": status.get("person_present"),
                "target": {k: status.get(k) for k in ("target_tracking", "target_box", "people_tracked")},
                "feed": feed.status()}

    @r.post("/simulate")
    def simulate(x_keepsake_local: str | None = Header(default=None)):
        # The custom header forces a CORS preflight, so other web pages can't trigger this.
        if x_keepsake_local != "1":
            raise HTTPException(403, "Send the X-Keepsake-Local: 1 header (local development only)")
        return feed.simulate(memory.view_id)

    return r
