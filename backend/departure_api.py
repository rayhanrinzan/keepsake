"""Departure Alerts endpoints, polled by the Photon Spectrum agent (integrations/photon).

The backend only reports possible departures and where items were last seen; the agent decides
whether a reminder is warranted and sends it. Keepsake keeps working if the agent is offline.
"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from departure import DepartureDetector, hold_reason
from spatial import place_phrase


class DepartureConfig(BaseModel):
    enabled: bool
    exit_zone: list[float] | None = None


def departure_router(detector: DepartureDetector, db, memory, modes, regions, get_worker) -> APIRouter:
    r = APIRouter(prefix="/api/departures")

    @r.get("")
    def list_departures(after: int = 0):
        return {"events": detector.events_after(after), "latest_id": detector.status()["latest_id"]}

    @r.get("/context")
    def context():
        """What the alert evaluator needs beyond /api/objects: is the view trustworthy right now,
        and the natural place phrase ("on the couch") for each item's last-seen area."""
        worker = get_worker()
        status = dict(worker.status) if worker else {"camera": "disabled"}
        places = {o["object_id"]: place_phrase(o["region"], regions)
                  for o in db.get_objects() if o.get("region")}
        return {"camera": status.get("camera"), "mode": modes.mode, "view_id": memory.view_id,
                "hold": hold_reason(modes, memory, status), "places": places,
                "detector": detector.status()}

    @r.put("/config")
    def put_config(cfg: DepartureConfig):
        try:
            return detector.configure(cfg.enabled, cfg.exit_zone)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e

    @r.post("/simulate")
    def simulate(x_keepsake_local: str | None = Header(default=None)):
        # The custom header forces a CORS preflight, so other web pages can't trigger this.
        if x_keepsake_local != "1":
            raise HTTPException(403, "Send the X-Keepsake-Local: 1 header (local development only)")
        return detector.simulate(memory.view_id)

    return r
