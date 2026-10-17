"""Parse a spoken or typed question into an intent and the configured item it names."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from rapidfuzz import fuzz, process

from lastseen.config import ItemCfg

Kind = Literal["find", "held_time", "enroll", "none"]


@dataclass
class Intent:
    kind: Kind
    item_id: str | None
    raw_item: str | None


_DET = r"(?:my |the |her |his |our )?"
_PATTERNS: list[tuple[Kind, re.Pattern[str]]] = [
    ("held_time", re.compile(rf"^when did i last (?:have|use|hold) {_DET}(?P<item>.+)$")),
    ("find", re.compile(rf"^(?:i )?can'?t find {_DET}(?P<item>.+)$")),
    ("find", re.compile(rf"^have you seen {_DET}(?P<item>.+)$")),
    ("enroll", re.compile(rf"^(?:please )?enroll {_DET}(?P<item>.+)$")),
    (
        "find",
        re.compile(rf"^where(?:'s| is| are| did i put| did i leave)? {_DET}(?P<item>.+)$"),
    ),
]
_FILLER = re.compile(r"(?:\s+(?:please|again|now|right now|at the moment|today))+$")


def _normalise(text: str) -> str:
    t = text.lower().replace("’", "'").replace("‘", "'")
    t = re.sub(r"\s+", " ", t).strip()
    return t.strip(" \t.,!?;:\"")


def _clean_item(phrase: str) -> str:
    p = phrase.strip(" .,!?;:\"")
    prev = None
    while prev != p:
        prev = p
        p = _FILLER.sub("", p).strip(" .,!?;:\"")
    return p


def _names(item: ItemCfg) -> list[str]:
    names = [*item.synonyms, item.id.replace("_", " "), item.display_name]
    return [_normalise(n) for n in names if n]


_FILLER_WORDS = {
    "my", "the", "a", "an", "her", "his", "our", "your", "please", "again", "now",
    "today", "at", "moment", "right",
}
_STOPWORDS = _FILLER_WORDS | {
    "is", "are", "was", "were", "you", "i", "we", "they", "it", "he", "she", "that",
    "this", "there", "here",
}


def _only_filler(rest: str) -> bool:
    return all(w in _FILLER_WORDS for w in rest.split())


def resolve_item(
    phrase: str, items: list[ItemCfg], *, fuzzy: bool = True, contain: bool = True
) -> str | None:
    phrase = _normalise(phrase)
    if not phrase:
        return None
    table: list[tuple[str, str]] = [(n, it.id) for it in items for n in _names(it)]
    for name, item_id in table:
        if name == phrase:
            return item_id
    if contain:
        best: tuple[int, str] | None = None
        for name, item_id in table:
            m = re.search(rf"\b{re.escape(name)}\b", phrase)
            if not m:
                continue
            rest = f"{phrase[: m.start()]} {phrase[m.end():]}"
            if _only_filler(rest) and (best is None or len(name) > best[0]):
                best = (len(name), item_id)
        if best:
            return best[1]
    if not fuzzy or not table:
        return None
    # Typos / spacing only: plain ratio, and similar length to the synonym.
    cands = [
        (fuzz.ratio(phrase, n), n, i)
        for n, i in table
        if 0.6 * len(n) <= len(phrase) <= 1.4 * len(n)
    ]
    cands = [c for c in cands if c[0] >= 80]
    if not cands:
        return None
    return max(cands, key=lambda c: c[0])[2]


def parse_question(text: str, items: list[ItemCfg]) -> Intent:
    norm = _normalise(text)
    for kind, pat in _PATTERNS:
        m = pat.match(norm)
        if m:
            raw = _clean_item(m.group("item"))
            words = raw.split()
            if not words or all(w in _STOPWORDS for w in words) or words[0] in _STOPWORDS - _FILLER_WORDS:
                continue
            return Intent(kind, resolve_item(raw, items), raw)
    stripped = text.strip()
    if stripped.endswith("?") and norm:
        item_id = resolve_item(_clean_item(norm), items, contain=False)
        if item_id:
            return Intent("find", item_id, _clean_item(norm))
    return Intent("none", None, None)
