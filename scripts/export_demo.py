#!/usr/bin/env python3
"""Build the hosted, recorded demo (demo_site/ + a recording of real, human-approved photos).

    .venv/bin/python scripts/export_demo.py backend/data/demo-recording backend/data/demo-site

`recording dir` holds photos/<id>.jpg and snapshots.json (rows from the snapshots table) that a
person checked one by one (no false hits, no people). Nothing is made up: every object, time, photo
and box comes from those rows, and each answer is built with the backend's own answer_query, plus
Amanda's Grok description of the newest photo (needs XAI_API_KEY in .env; skipped without it).

The output dir gets the mobile web build (built with EXPO_PUBLIC_API_URL=same-origin), demo_site's
serverless API and vercel.json, the photos, and api/recording.json. Deploy it with `vercel deploy`.
It's under backend/data/, so photos never go into git.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from catalog import ALIASES, CATALOG  # noqa: E402
from describe import SceneDescriber  # noqa: E402
from memory import answer_query  # noqa: E402
from voice import DEFAULT_VOICES, load_env_file  # noqa: E402

FAR_FUTURE = datetime(2100, 1, 1, tzinfo=timezone.utc)  # answers say "on Oct 18 at 2:12 AM", never "at"


def snapshot_view(s: dict) -> dict:
    return {"id": s["id"], "object_id": s["object_id"], "event_type": s["event_type"],
            "timestamp": s["timestamp"], "bbox": [s["x0"], s["y0"], s["x1"], s["y1"]],
            "confidence": s["confidence"], "image_url": f"/api/snapshots/{s['id']}/image"}


def main(rec_dir: Path, out: Path) -> None:
    load_env_file(ROOT / ".env")
    rows = json.loads((rec_dir / "snapshots.json").read_text())
    by_item: dict[str, list[dict]] = {}
    for r in sorted(rows, key=lambda r: r["timestamp"], reverse=True):
        by_item.setdefault(r["object_id"], []).append(r)

    describer = SceneDescriber()
    # Descriptions are kept with the recording, so a rebuild says the same thing and costs nothing.
    saved_path = rec_dir / "descriptions.json"
    saved = json.loads(saved_path.read_text()) if saved_path.exists() else {}
    objects, snaps, answers, notes = [], {}, {}, {}
    for item in CATALOG:
        mine = by_item.get(item["object_id"], [])
        base = {"object_id": item["object_id"], "category": item["category"], "name": item["name"], "icon": item["icon"]}
        if not mine:
            obj = {**base, "seen": False, "status": "never", "last_seen": None, "visible": False,
                   "confidence": None, "snapshot": None}
        else:
            newest = mine[0]
            obj = {**base, "seen": True, "status": "last_seen", "last_seen": newest["timestamp"], "visible": False,
                   "confidence": newest["confidence"], "snapshot": snapshot_view(newest)}
        objects.append(obj)
        snaps[item["object_id"]] = [snapshot_view(s) for s in mine]

        def describe(o, noun, newest=mine[0] if mine else None):
            if newest is None:
                return None
            if str(newest["id"]) not in saved:
                saved[str(newest["id"])] = describer.describe(newest["id"], rec_dir / "photos" / f"{newest['id']}.jpg", noun,
                                                              [newest["x0"], newest["y0"], newest["x1"], newest["y1"]])
            return saved[str(newest["id"])]

        import memory  # the recorded times are always "on Oct 18 at …"
        real = memory.spoken_time
        memory.spoken_time = lambda iso, now=None: real(iso, FAR_FUTURE)
        try:
            r = answer_query(f"where is my {item['name'].lower()}", lambda cat, o=obj: o, describe)
        finally:
            memory.spoken_time = real
        answers[item["category"]] = r["answer"]
        notes[item["name"]] = r.get("surroundings")

    saved_path.write_text(json.dumps(saved, indent=1))
    unknown = answer_query("where is my umbrella", lambda cat: None)["answer"]
    events = [{"id": i, "object_id": s["object_id"], "name": next(c["name"] for c in CATALOG if c["object_id"] == s["object_id"]),
               "event_type": "object_observed" if s["event_type"] == "seen" else s["event_type"],
               "timestamp": s["timestamp"], "confidence": s["confidence"]}
              for i, s in enumerate(sorted(rows, key=lambda r: r["timestamp"], reverse=True), 1)]

    # Same voices the local backend offers (it asks xAI); fall back to the built-in list.
    try:
        import urllib.request
        voice = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/voice", timeout=3))
    except Exception:  # noqa: BLE001
        voice = {"provider": "grok", "voice_id": "eve", "speed": 1.0, "voices": DEFAULT_VOICES}

    recording = {
        "recorded": min(r["timestamp"] for r in rows)[:10],
        "objects": objects, "snapshots": snaps, "events": events, "answers": answers,
        "aliases": ALIASES, "unknown": unknown,
        "voice": {"provider": voice.get("provider", "grok"), "voice_id": voice.get("voice_id", "eve"),
                  "speed": voice.get("speed", 1.0), "voices": voice.get("voices", DEFAULT_VOICES)},
    }

    if out.exists():
        shutil.rmtree(out)
    mobile = ROOT / "mobile"
    subprocess.run(["npx", "expo", "export", "--platform", "web", "--output-dir", str(out)], cwd=mobile, check=True,
                   env={**__import__("os").environ, "CI": "1", "EXPO_PUBLIC_API_URL": "same-origin"},
                   stdout=subprocess.DEVNULL)
    # Vercel never uploads folders named node_modules, and Expo puts the fonts in one: move them;
    # vercel.json rewrites the old paths.
    if (out / "assets" / "node_modules").exists():
        (out / "assets" / "node_modules").rename(out / "assets" / "nm")
    shutil.copytree(ROOT / "demo_site" / "api", out / "api")
    shutil.copy(ROOT / "demo_site" / "vercel.json", out / "vercel.json")
    shutil.copytree(rec_dir / "photos", out / "photos")
    (out / "api" / "recording.json").write_text(json.dumps(recording, indent=1))
    print(f"demo site in {out}: {len(rows)} photos, {sum(o['seen'] for o in objects)}/{len(objects)} items")
    for name, sentence in notes.items():
        print(f"  {name}: {sentence or '(no description)'}")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
