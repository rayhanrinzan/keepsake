"""Chalk AI Router client (OpenAI-compatible). Optional: facts never come from here.

Used only to (a) map an oddly-phrased question to a configured item id and
(b) reword a template answer. Text only; any problem -> None / the template.
"""
from __future__ import annotations

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path

log = logging.getLogger("lastseen.llm")

_TIME_RE = re.compile(r"(?<![\d:])\d{1,2}:\d{2}\s?[AP]M(?!\w)", re.I)
_ANY_TIME_RE = re.compile(r"(?<![\d:])\d{1,2}(?::\d{2}\s?(?:[AP]M)?|\s?[AP]M)(?!\w)", re.I)
_NEG_RE = re.compile(r"\b(?:not|never|no longer|nowhere|cannot|can't|isn't|aren't|don't|didn't|won't)\b|n't\b", re.I)
_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="chalk")


class ChalkLLM:
    def __init__(self, host, key, env_id, model, timeout_s=2.5, client=None):
        self.host, self.model, self.timeout_s = host, model, timeout_s
        self.last_ok: bool | None = None
        self.on_status = None  # optional callable("ok" | "error")
        if client is None:
            import httpx
            from openai import OpenAI

            headers = {"X-Chalk-Env-Id": env_id} if env_id else {}
            client = OpenAI(base_url=f"https://{host}/v1/router", api_key=key,
                            default_headers=headers, max_retries=0,
                            timeout=httpx.Timeout(timeout_s, connect=1.0))
        self.client = client

    @classmethod
    def from_env(cls, dotenv_path=None) -> "ChalkLLM | None":
        try:
            from dotenv import load_dotenv

            p = Path(dotenv_path) if dotenv_path else Path(".env")
            if p.is_file():
                load_dotenv(p, override=False)
        except Exception:
            log.exception("could not load .env")
        key = os.environ.get("CHALK_ROUTER_KEY")
        host = os.environ.get("CHALK_API_HOST")
        model = os.environ.get("CHALK_MODEL")  # docs name no default model: required
        if not (key and host and model):
            return None
        return cls(host, key, os.environ.get("CHALK_ENV_ID") or None, model)

    # ------------------------------------------------------------------ plumbing
    def _set(self, ok: bool) -> None:
        self.last_ok = ok
        if self.on_status is not None:
            try:
                self.on_status("ok" if ok else "error")
            except Exception:
                log.exception("on_status failed")

    def _call(self, timeout_s: float | None = None, **kw):
        fut = _POOL.submit(self.client.chat.completions.create, model=self.model, **kw)
        try:
            resp = fut.result(timeout=self.timeout_s if timeout_s is None else timeout_s)
        except FutureTimeout:
            fut.cancel()
            raise TimeoutError("chalk router timed out") from None
        return resp.choices[0].message

    # ------------------------------------------------------------------ public
    def parse_item(self, question: str, items, timeout_s: float | None = None) -> str | None:
        ids = [i.id for i in items]
        catalog = [{"id": i.id, "name": i.display_name, "synonyms": list(i.synonyms)} for i in items]
        tool = {"type": "function", "function": {
            "name": "get_item_status",
            "description": "Look up which of the user's tracked items the question is about.",
            "parameters": {"type": "object", "required": ["item_id"],
                           "properties": {"item_id": {"type": "string", "enum": ids}}}}}
        try:
            msg = self._call(
                timeout_s,
                messages=[
                    {"role": "system", "content": "Pick which tracked item the user is asking about. "
                     "Call get_item_status with its id. If none fit, reply with the word none."},
                    {"role": "user", "content": json.dumps({"question": question, "items": catalog})}],
                tools=[tool],
                tool_choice={"type": "function", "function": {"name": "get_item_status"}},
                max_tokens=60, temperature=0)
            found = None
            for tc in getattr(msg, "tool_calls", None) or []:
                found = json.loads(tc.function.arguments).get("item_id")
                break
            if found is None and getattr(msg, "content", None):
                found = json.loads(msg.content).get("item_id")
            self._set(True)
        except Exception as e:
            log.warning("chalk parse_item failed: %s", type(e).__name__)
            # unparseable replies (bad JSON/shape) mean the router answered: still reachable
            self._set(isinstance(e, (ValueError, AttributeError, TypeError)))
            return None
        return found if found in ids else None

    def reword(self, template_text: str, facts: dict, timeout_s: float | None = None) -> str:
        safe = {k: facts.get(k) for k in ("item_id", "state", "zone", "uncertain")}
        try:
            msg = self._call(
                timeout_s,
                messages=[
                    {"role": "system", "content": "Reword the sentence to sound warm and brief for an "
                     "older person. Keep every fact (place, time, hedges like 'I think') exactly. "
                     "Add nothing. Reply with the sentence only."},
                    {"role": "user", "content": json.dumps({"text": template_text, "facts": safe})}],
                max_tokens=120, temperature=0.3)
            out = (msg.content or "").strip().strip("\"'“”").strip()
            self._set(True)
        except Exception as e:
            log.warning("chalk reword failed: %s", type(e).__name__)
            self._set(False)
            return template_text
        return out if self._keeps_facts(template_text, facts, out) else template_text

    @staticmethod
    def _keeps_facts(template: str, facts: dict, out: str) -> bool:
        if not out or len(out) > 2 * len(template) + 40:
            return False
        low = out.lower()
        zone = (facts.get("zone") or "").replace("_", " ").lower()
        for w in zone.split():
            if not re.search(rf"(?<!\w){re.escape(w)}(?!\w)", low):
                return False
        # times: every template time present exactly, and no other time-like token
        want = {re.sub(r"\s", "", t.lower()) for t in _TIME_RE.findall(template)}
        got = {re.sub(r"\s", "", t.group(0).lower()) for t in _ANY_TIME_RE.finditer(out)}
        if got != want:
            return False
        if template.startswith("I think") and "i think" not in low:
            return False
        if _NEG_RE.search(low) and not _NEG_RE.search(template.lower()):
            return False
        return True
