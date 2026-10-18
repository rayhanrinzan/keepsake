"""Deterministic answers from the store. Facts come from the database, never from an LLM."""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from pathlib import Path

from lastseen.brain.intents import Intent, parse_question
from lastseen.vision.identity import Gallery

log = logging.getLogger("lastseen.answer")

ERROR_TEXT = "Sorry, something went wrong — try asking again."
NO_INTENT_TEXT = "Sorry, I didn't catch which of your things you mean."
_SNAP_KINDS = ("PLACED", "SEEN", "HIDDEN", "CARRIED_OUT")
LLM_BUDGET_S = 2.5        # parse_item + reword together, per ask
VOICE_REWORD_S = 1.0      # a spoken answer should start fast: shorter reword budget
MIN_LLM_S = 0.1           # not worth a call with less time than this left
_FAST_SOURCES = ("voice", "proactive")   # spoken answers: shorter reword budget
_AUTO = object()          # _finish: pick the latest snapshot event


def fmt_time(ts: float | None) -> str:
    if ts is None:
        return "earlier"
    return datetime.fromtimestamp(ts).strftime("%-I:%M %p")


def fmt_ago(ts: float | None, now: float) -> str:
    if ts is None:
        return "earlier"
    secs = now - ts
    if secs < 60:
        return "just now"
    if secs < 3600:
        m = int(secs // 60)
        return "1 minute ago" if m == 1 else f"{m} minutes ago"
    return "at " + fmt_time(ts)


def _plural(name: str) -> bool:
    return name.strip().lower().endswith("s")


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]


class AnswerEngine:
    def __init__(self, cfg, store, zones, llm=None, bus=None, frame_wh=None, enroll_fn=None):
        self.cfg, self.store, self.zones = cfg, store, zones
        self.llm, self.bus = llm, bus
        self.frame_wh, self.enroll_fn = frame_wh, enroll_fn
        self.gallery_root = Path(cfg.paths.data) / "gallery"
        self._req = threading.local()  # per-ask deadline + source (asks arrive on several threads)

    # ------------------------------------------------------------------ helpers
    def _wh(self) -> tuple[int, int]:
        wh = None
        if self.frame_wh is not None:
            try:
                wh = self.frame_wh()
            except Exception:
                log.exception("frame_wh failed")
        if wh:
            return int(wh[0]), int(wh[1])
        w = self.cfg.camera.width
        return w, round(w * 9 / 16)

    def _cfg_item(self, item_id: str):
        return next((i for i in self.cfg.items if i.id == item_id), None)

    def _phrase(self, bbox) -> str:
        if not bbox:
            return "in the room"
        return self.zones.describe(tuple(bbox), self._wh())

    def _budget(self, cap: float | None = None) -> float:
        """Seconds left of this ask's shared LLM budget (optionally capped)."""
        left = max(0.0, getattr(self._req, "deadline", 0.0) - time.monotonic())
        return min(left, cap) if cap is not None else left

    def _llm_on(self) -> bool:
        return self.llm is not None and bool(self.cfg.features.chalk_llm)

    def _snapshot(self, item_id: str) -> dict | None:
        for ev in self.store.recent_events(50, item_id):
            if ev["kind"] in _SNAP_KINDS and ev["snapshot_url"]:
                return ev
        return None

    def _snapshot_since(self, item_id: str, since: float | None) -> dict | None:
        """Latest snapshot event at or after `since` (the current placement); None without one."""
        if since is None:
            return None
        for ev in self.store.recent_events(50, item_id):
            if ev["ts"] < since:
                continue
            if ev["kind"] in _SNAP_KINDS and ev["snapshot_url"]:
                return ev
        return None

    # ------------------------------------------------------------------ public
    def ask(self, question: str, source: str) -> dict:
        return self._run(question, source, lambda: self._answer(question))

    def answer_item(self, item_id: str, source: str) -> dict:
        """Answer for a known item, skipping question parsing."""
        return self._run(f"[{source}] {item_id}", source, lambda: self._answer_known(item_id))

    def _run(self, question: str, source: str, fn) -> dict:
        t0 = time.monotonic()
        self._req.deadline, self._req.source = t0 + LLM_BUDGET_S, source
        publish = True
        try:
            res, publish = fn()
        except Exception:
            log.exception("answer failed for %r", question)
            res = self._result(ERROR_TEXT, None, None, None, False)
        res["display_name"] = self._display_name(res["item_id"])
        res["latency_ms"] = int((time.monotonic() - t0) * 1000)
        try:
            self.store.add_ask(source, question, res["item_id"], res["text"], res["state"],
                               res["zone"], res["latency_ms"])
        except Exception:
            log.exception("could not log ask")
        if publish and self.bus is not None:
            try:
                self.bus.publish("show_answer", answer=res)
            except Exception:
                log.exception("could not publish show_answer")
        return res

    def _display_name(self, item_id: str | None) -> str | None:
        if item_id is None:
            return None
        icfg = self._cfg_item(item_id)
        try:
            row = self.store.get_item(item_id)
        except Exception:
            row = None
        return (icfg.display_name if icfg else None) or (row or {}).get("display_name") or item_id

    @staticmethod
    def _result(text, item_id, state, zone, uncertain, row=None, snap=None) -> dict:
        return {
            "text": text, "item_id": item_id, "state": state, "zone": zone,
            "uncertain": bool(uncertain),
            "snapshot_url": snap["snapshot_url"] if snap else None,
            "clip_url": snap["clip_url"] if snap else None,
            "ts_placed": row["last_seen_ts"] if row else None,
            "latency_ms": 0,
        }

    def _answer(self, question: str) -> tuple[dict, bool]:
        intent = parse_question(question, self.cfg.items)
        if self._llm_on() and (intent.kind == "none" or intent.item_id is None):
            try:
                budget = self._budget()
                found = (self.llm.parse_item(question, self.cfg.items, timeout_s=budget)
                         if budget >= MIN_LLM_S else None)
                if found and self._cfg_item(found):
                    kind = intent.kind if intent.kind != "none" else "find"
                    intent = Intent(kind, found, intent.raw_item)
            except Exception:
                log.exception("llm parse_item failed")
        if intent.kind == "none":
            return self._result(NO_INTENT_TEXT, None, None, None, False), False
        if intent.item_id is None:
            text = f"I'm not tracking anything called {intent.raw_item} yet."
            return self._result(text, None, None, None, False), True
        item_id = intent.item_id
        icfg, row, name, it = self._item_ctx(item_id)

        if intent.kind == "enroll":
            return self._enroll(item_id, name), True
        if intent.kind == "held_time":
            ev = self.store.last_event(item_id, ("PICKED_UP",))
            text = (f"You last picked up your {name} at {fmt_time(ev['ts'])}." if ev
                    else f"I haven't seen you pick up your {name}.")
            if ev and ev["uncertain"]:
                text = "I think " + _lower_first(text)
            return self._finish(text, item_id, row, ev["uncertain"] if ev else False,
                                row["state"] if row else None), True
        return self._find(item_id, name, it, row), True

    def _item_ctx(self, item_id: str):
        icfg = self._cfg_item(item_id)
        row = self.store.get_item(item_id)
        name = (icfg.display_name if icfg else None) or (row or {}).get("display_name") or item_id
        return icfg, row, name, ("them" if _plural(name) else "it")

    def _answer_known(self, item_id: str) -> tuple[dict, bool]:
        _, row, name, it = self._item_ctx(item_id)
        return self._find(item_id, name, it, row), True

    def _enroll(self, item_id: str, name: str) -> dict:
        if self.enroll_fn is None:
            text = "I can't learn new things right now."
        else:
            try:
                self.enroll_fn(item_id, name)
                text = "OK, pick it up and put it down where I can see it."
            except Exception:
                log.exception("enroll_fn failed")
                text = ERROR_TEXT
        return self._result(text, item_id, None, None, False)

    def _find(self, item_id: str, name: str, it: str, row: dict | None) -> dict:
        state = row["state"] if row else "UNKNOWN"
        zone = row["zone"] if row else None
        wearable = self.cfg.camera.mode == "wearable"
        icfg = self._cfg_item(item_id)
        events = [] if wearable else self.store.recent_events(1, item_id)
        snap, reword = _AUTO, True
        if wearable and (state == "UNKNOWN" or (icfg is not None and not icfg.enabled)):
            text, unc = f"Sorry, I did not see you interact with your {name}.", False
            snap = None                   # an old-session photo would contradict the sentence
        elif wearable and state == "PLACED":
            ev = self.store.last_event(item_id, ("PLACED",))
            ts = ev["ts"] if ev else row["last_seen_ts"]
            text = (f"You put your {name} down {fmt_ago(ts, time.time())}. "
                    "I put a photo of where on the screen.")
            unc = bool(ev["uncertain"]) if ev else bool(row["uncertain"])
            snap = self._snapshot_since(item_id, ev["ts"] if ev else None)
            reword = False                # template only, so the photo sentence survives
        elif wearable and state == "CARRIED_OUT":
            ev = self.store.last_event(item_id, ("CARRIED_OUT",))
            ts = ev["ts"] if ev else row["last_seen_ts"]
            text = f"You picked up your {name} at {fmt_time(ts)} and had {it} with you."
            unc = bool(ev["uncertain"]) if ev else False
            snap = None                   # an out-of-view photo would circle an empty spot
        elif not wearable and not events and Gallery.load(item_id, self.gallery_root) is None:
            text, unc = f"I haven't been shown your {name} yet.", False
        elif state == "HELD":
            text, unc = f"You're holding {it} right now.", bool(row and row["uncertain"])
        elif state == "HIDDEN":
            ev = self.store.last_event(item_id, ("HIDDEN",))
            ts = ev["ts"] if ev else row["last_seen_ts"]
            phrase = self._phrase((ev or row)["bbox"])
            probably = "They're" if it == "them" else "It's"
            text = f"I last saw your {name} going {phrase} at {fmt_time(ts)}. {probably} probably still there."
            unc = bool(ev["uncertain"]) if ev else False
        elif state == "CARRIED_OUT":
            ev = self.store.last_event(item_id, ("CARRIED_OUT",))
            ts = ev["ts"] if ev else row["last_seen_ts"]
            text = f"You picked up your {name} at {fmt_time(ts)} and took {it} out of view."
            unc = bool(ev["uncertain"]) if ev else False
        elif state == "PLACED":
            ev = self.store.last_event(item_id, ("PLACED", "SEEN"))
            ts = ev["ts"] if ev else row["last_seen_ts"]
            phrase = self._phrase(row["bbox"] or (ev or {}).get("bbox"))
            be = "are" if it == "them" else "is"
            text = f"Your {name} {be} {phrase}. You put {it} there at {fmt_time(ts)}."
            unc = bool(ev["uncertain"]) if ev else bool(row["uncertain"])
        else:
            ev = self.store.last_event(item_id, ("PLACED",))
            if ev:
                text = (f"I can't see your {name} right now. I last saw {it} "
                        f"{self._phrase(ev['bbox'])} at {fmt_time(ev['ts'])}.")
                unc = bool(ev["uncertain"])
            else:
                text, unc = f"I haven't seen your {name} since you showed {it} to me.", False
        if unc:
            text = "I think " + _lower_first(text)
        return self._finish(text, item_id, row, unc, state, snap=snap, reword=reword)

    def _finish(self, text, item_id, row, unc, state, snap=_AUTO, reword=True) -> dict:
        fast = getattr(self._req, "source", None) in _FAST_SOURCES
        budget = self._budget(VOICE_REWORD_S if fast else None)
        if reword and self._llm_on() and budget >= MIN_LLM_S:
            facts = {"item_id": item_id, "state": state, "zone": row["zone"] if row else None,
                     "uncertain": bool(unc)}
            try:
                worded = self.llm.reword(text, facts, timeout_s=budget)
                if isinstance(worded, str) and worded.strip():
                    text = worded.strip()
            except Exception:
                log.exception("llm reword failed")
        if snap is _AUTO:
            snap = self._snapshot(item_id)
        return self._result(text, item_id, state, row["zone"] if row else None, unc, row, snap)
