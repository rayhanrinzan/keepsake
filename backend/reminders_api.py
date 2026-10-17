"""Smart memory reminder endpoints (local only), used by the Photon Spectrum agent.

Reads are open on localhost like the rest of the API. Every write needs the X-Keepsake-Local
header, which forces a CORS preflight so other web pages can't change settings or queue messages.
Recipient numbers never reach the backend; they stay in the agent's .env.
"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from reminders import EventError, ReminderEngine


class SettingsIn(BaseModel):
    mode: str | None = None
    enabled: bool | None = None
    opt_in: bool = False
    important: list[str] | None = None
    overrides: dict[str, dict[str, float]] | None = None


class CheckIn(BaseModel):
    reason: str = "manual"


class ResultIn(BaseModel):
    status: str
    error: str | None = None


class AckIn(BaseModel):
    action: str
    alert_id: int | None = None


def _local(header: str | None) -> None:
    if header != "1":
        raise HTTPException(403, "Send the X-Keepsake-Local: 1 header (local only)")


def reminders_router(engine: ReminderEngine) -> APIRouter:
    r = APIRouter(prefix="/api/reminders")

    @r.get("/settings")
    def get_settings():
        return engine.status()

    @r.put("/settings")
    def put_settings(body: SettingsIn, x_keepsake_local: str | None = Header(default=None)):
        _local(x_keepsake_local)
        changes = body.model_dump(exclude_none=True, exclude={"opt_in"})
        try:
            return engine.update_settings(changes, opt_in=body.opt_in)
        except PermissionError as e:
            raise HTTPException(409, str(e)) from e
        except ValueError as e:
            raise HTTPException(422, str(e)) from e

    @r.post("/events")
    def post_event(event: dict, x_keepsake_local: str | None = Header(default=None)):
        _local(x_keepsake_local)
        try:
            return engine.submit(event)
        except EventError as e:
            raise HTTPException(422, str(e)) from e

    @r.post("/check")
    def check(body: CheckIn, x_keepsake_local: str | None = Header(default=None)):
        _local(x_keepsake_local)
        try:
            return engine.check(body.reason)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e

    @r.get("/alerts")
    def alerts(status: str = "queued"):
        return engine.alerts(None if status == "all" else status)

    @r.post("/alerts/{alert_id}/claim")
    def claim(alert_id: int, x_keepsake_local: str | None = Header(default=None)):
        _local(x_keepsake_local)
        try:
            return engine.claim(alert_id)
        except KeyError as e:
            raise HTTPException(404, "No such alert") from e
        except PermissionError as e:
            raise HTTPException(409, str(e)) from e

    @r.post("/alerts/{alert_id}/result")
    def result(alert_id: int, body: ResultIn, x_keepsake_local: str | None = Header(default=None)):
        _local(x_keepsake_local)
        try:
            return engine.report(alert_id, body.status, body.error)
        except KeyError as e:
            raise HTTPException(404, "No such alert") from e
        except PermissionError as e:
            raise HTTPException(409, str(e)) from e
        except ValueError as e:
            raise HTTPException(422, str(e)) from e

    @r.post("/ack")
    def ack(body: AckIn, x_keepsake_local: str | None = Header(default=None)):
        _local(x_keepsake_local)
        try:
            return engine.acknowledge(body.action, body.alert_id)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e

    return r
