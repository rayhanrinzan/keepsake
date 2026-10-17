"""LostSightAsker: asks "Are you looking for your X?" when a put-down item stays out of view.

Pure decision logic (no audio, no models) plus a small thread body, `run_asker`. One internal lock
guards the state because `tick`, `on_text` and `dismiss` arrive on different threads; `say` and
`answer_item` are always called outside it, since they may block briefly.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable, Literal

from lastseen.bus import Bus
from lastseen.config import ItemCfg, WearableCfg
from lastseen.engine.wear_tracker import WearStatus
from lastseen.brain.intents import parse_question, resolve_item

logger = logging.getLogger(__name__)

_NO = re.compile(r"\bno\b|\bnope\b|\bi know\b|\bi'?m fine\b|\bi'?m good\b|\bnot really\b|\bnot sure\b|\bnever ?mind\b")
_YES = re.compile(r"\b(?:yes|yeah|yep|yup|i am|sure|please|where)\b")


def parse_reply(text: str) -> Literal["yes", "no"] | None:
    t = text.lower().replace("’", "'")
    if _NO.search(t):
        return "no"
    if _YES.search(t):
        return "yes"
    return None


def _scan_item(text: str, items: list[ItemCfg]) -> str | None:
    """Longest whole-word/phrase match of any item name in free text (leftover words ignored)."""
    norm = " " + re.sub(r"[^a-z0-9']+", " ", text.lower().replace("’", "'")).strip() + " "
    best: tuple[int, str] | None = None
    for it in items:
        for name in [*it.synonyms, it.display_name, it.id.replace("_", " ")]:
            n = re.sub(r"[^a-z0-9']+", " ", name.lower()).strip()
            if n and f" {n} " in norm and (best is None or len(n) > best[0]):
                best = (len(n), it.id)
    return best[1] if best else None


@dataclass
class _Dialog:
    stage: str                       # single | group | which
    ids: list[str]
    deadline: float | None = None
    opened: float = 0.0


class LostSightAsker:
    def __init__(self, cfg: WearableCfg, items: list[ItemCfg], say: Callable[[str], None],
                 is_speaking: Callable[[], bool], answer_item: Callable[[str, str], dict],
                 clock: Callable[[], float] = time.monotonic):
        self.cfg, self.items = cfg, items
        self._say, self._is_speaking, self._answer = say, is_speaking, answer_item
        self._clock = clock
        self._lock = threading.Lock()
        self._statuses: dict[str, WearStatus] = {}
        self._baseline: dict[str, float] = {}
        self._sightings: dict[str, int] = {}
        self._silenced: set[str] = set()
        self._dialog: _Dialog | None = None

    # -- helpers (call with the lock held) --
    def _eff(self, s: WearStatus) -> float:
        return max(0.0, s.unseen_s - self._baseline.get(s.item_id, 0.0))

    def _display(self, item_id: str) -> str:
        s = self._statuses.get(item_id)
        if s and s.display_name:
            return s.display_name
        for it in self.items:
            if it.id == item_id:
                return it.display_name
        return item_id

    def _flush(self, actions: list[tuple[str, str]]) -> None:
        for kind, val in actions:
            try:
                if kind == "ans":
                    self._say(self._answer(val, "proactive")["text"])
                else:
                    self._say(val)
            except Exception:
                logger.exception("lost-sight action failed")

    def _pick_item(self, text: str) -> str | None:
        intent = parse_question(text, self.items)
        if intent.kind == "find" and intent.item_id:
            return intent.item_id
        return None

    def _close_timeout(self, d: _Dialog, extra: str | None = None) -> None:
        """Close the dialog and re-arm its items only after another ask_after_s unseen."""
        for i in [*d.ids, *([extra] if extra else [])]:
            if i in self._statuses:
                self._baseline[i] = self._statuses[i].unseen_s
        self._dialog = None

    # -- public --
    def tick(self, statuses: list[WearStatus], fresh: bool) -> None:
        actions: list[tuple[str, str]] = []
        with self._lock:
            now = self._clock()
            self._statuses = {s.item_id: s for s in statuses}
            for s in statuses:
                prev = self._sightings.get(s.item_id)
                if prev is not None and prev != s.sightings:
                    self._baseline[s.item_id] = 0.0
                    self._silenced.discard(s.item_id)
                self._sightings[s.item_id] = s.sightings
                if s.phase != "PLACED_GONE":
                    self._baseline[s.item_id] = 0.0
                    self._silenced.discard(s.item_id)
            speaking = self._is_speaking()
            d = self._dialog
            if d is not None:
                if speaking:
                    d.deadline = None
                elif d.deadline is None:
                    d.deadline = now + self.cfg.reply_window_s
                elif now > d.deadline:
                    self._close_timeout(d)
                if self._dialog is d and now - d.opened > self.cfg.reply_window_s + 30:
                    self._close_timeout(d)
            if self._dialog is None and fresh and not speaking:
                eligible = [s for s in statuses if s.phase == "PLACED_GONE" and s.item_id not in self._silenced]
                if any(self._eff(s) >= self.cfg.ask_after_s for s in eligible):
                    group = [s for s in eligible
                             if self._eff(s) >= self.cfg.ask_after_s - self.cfg.group_window_s]
                    if len(group) == 1:
                        self._dialog = _Dialog("single", [group[0].item_id], opened=now)
                        actions.append(("say", f"Are you looking for your {self._display(group[0].item_id)}?"))
                    else:
                        self._dialog = _Dialog("group", [s.item_id for s in group], opened=now)
                        actions.append(("say", "Are you looking for something?"))
        self._flush(actions)

    def on_text(self, text: str) -> bool:
        actions: list[tuple[str, str]] = []
        with self._lock:
            d = self._dialog
            if d is None:
                return False
            item = self._pick_item(text)
            if item:
                actions.append(("ans", item))
                self._close_timeout(d, item)
            elif d.stage == "which":
                found = resolve_item(text, self.items) or _scan_item(text, self.items)
                if found:
                    actions.append(("ans", found))
                elif parse_reply(text) != "no":
                    actions.append(("say", "Sorry, I didn't catch that."))
                self._close_timeout(d, found)
            else:
                reply = parse_reply(text)
                if reply is None:
                    return False
                if reply == "no":
                    self._silenced.update(d.ids)
                    self._dialog = None
                elif d.stage == "single":
                    actions.append(("ans", d.ids[0]))
                    self._close_timeout(d)
                else:
                    d.stage, d.deadline = "which", None
                    actions.append(("say", "OK, what item are you looking for?"))
        self._flush(actions)
        return True

    def dismiss(self, item_id: str) -> bool:
        with self._lock:
            s = self._statuses.get(item_id)
            if s is None or s.phase == "UNTRACKED":
                return False
            self._silenced.add(item_id)
            d = self._dialog
            if d is not None and item_id in d.ids:
                d.ids.remove(item_id)
                if not d.ids:
                    self._dialog = None
            return True

    def view(self) -> dict[str, dict]:
        with self._lock:
            asking = set(self._dialog.ids) if self._dialog else set()
            return {i: {"unseen_s": self._eff(s), "silenced": i in self._silenced, "asking": i in asking}
                    for i, s in self._statuses.items()}


def run_asker(asker: LostSightAsker, loop, bus: Bus, stop: threading.Event, period: float = 0.25) -> None:
    n = 0
    while not stop.is_set():
        try:
            statuses, fresh = loop.wear_status()
            asker.tick(statuses, fresh)
            n += 1
            if n % 2 == 0:
                v = asker.view()
                none: dict = {}
                items = []
                for s in statuses:
                    iv = v.get(s.item_id, none)
                    items.append({"id": s.item_id, "display_name": s.display_name, "phase": s.phase,
                                  "unseen_s": iv.get("unseen_s", s.unseen_s), "last_seen_ts": s.last_seen_ts,
                                  "silenced": iv.get("silenced", False), "asking": iv.get("asking", False)})
                bus.publish("wear_status", items=items, camera_lost=not fresh,
                            config_ids=[it.id for it in asker.items])
        except Exception:
            logger.exception("lost-sight asker step failed")
        stop.wait(period)
