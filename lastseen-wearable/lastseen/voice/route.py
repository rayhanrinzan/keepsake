"""Routes a transcript: questions are answered aloud, everything else is discarded."""
from __future__ import annotations

import logging

from lastseen.brain.intents import parse_question

logger = logging.getLogger(__name__)

QUESTION_KINDS = ("find", "held_time", "enroll")


def make_on_text(engine, speaker, items, dialog=None):
    def on_text(text: str) -> bool:
        if dialog is not None:
            try:
                if dialog.on_text(text):
                    return True
            except Exception:
                logger.exception("lost-sight dialog failed on text; routing normally")
        if parse_question(text, items).kind not in QUESTION_KINDS:
            return False
        res = engine.ask(text, "voice")  # the engine logs every ask
        if res.get("item_id") is not None:  # an unknown item / no item: stay quiet
            speaker.say(res["text"])
        return True

    return on_text
