"""Entry point: python -m lastseen"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

from lastseen.config import load_config

log = logging.getLogger("lastseen")
SHUTDOWN_GRACE_S = 2


class JsonlHandler(logging.Handler):
    def __init__(self, path: Path):
        super().__init__()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._f = open(path, "a", buffering=1)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            row = {
                "ts": record.created,
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
            }
            if record.exc_info:
                row["exc"] = record.exc_text or logging.Formatter().formatException(record.exc_info)
            self._f.write(json.dumps(row) + "\n")
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        try:
            self._f.close()
        finally:
            super().close()


def setup_logging(data_dir: str) -> Path:
    path = Path(data_dir) / "logs" / f"session-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(console)
    root.addHandler(JsonlHandler(path))
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)  # "Processing audio..." every 1.5 s
    return path


def server_config(app, port: int):
    """uvicorn config for the app. log_config=None: uvicorn's default dictConfig would close every
    handler already installed (including the session log file) while the app keeps logging."""
    import uvicorn

    return uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning", log_config=None,
                          timeout_graceful_shutdown=SHUTDOWN_GRACE_S)



def _cleanup_loop(clips_dir: Path, stop: "threading.Event", interval: float = 3600.0) -> None:
    from lastseen.memory.clips import cleanup_old

    while True:
        try:
            n = cleanup_old(clips_dir)
            if n:
                log.info("cleanup removed %d old clip files", n)
        except Exception:
            log.exception("clip cleanup failed")
        if stop.wait(interval):
            return


def _make_people(cfg, factory=None):
    """The person tracker, or None (off, or failed to load: the item tracker uses the frame edge)."""
    if not cfg.features.people_tracking:
        log.info("people tracking off")
        return None
    try:
        if factory is None:
            from lastseen.vision.people import PeopleTracker as factory
        return factory(cfg.persons, cfg.device)
    except Exception:
        log.exception("people tracker failed to load; using the frame-edge fallback")
        return None


def _start_asker(cfg, loop, speaker, engine, bus, stop: threading.Event, ctx):
    """Build and start the lost-sight asker (wearable mode only). Returns (asker, thread) or (None, None)."""
    if not (cfg.features.lost_sight_ask and loop is not None and cfg.camera.mode == "wearable"):
        return None, None
    from lastseen.proactive.lost_sight import LostSightAsker, run_asker

    # All config items, so the which-stage recognises disabled ones too; asking is still
    # limited to items with a wear status.
    dialog = LostSightAsker(
        cfg.wearable, list(cfg.items), speaker.say,
        lambda: speaker.speaking.is_set() or time.monotonic() < speaker.muted_until() + 2.5,
        engine.answer_item)
    ctx.dismiss_fn = lambda i: {"ok": dialog.dismiss(i)}
    th = threading.Thread(target=run_asker, args=(dialog, loop, bus, stop), name="lost-sight", daemon=True)
    th.start()
    log.info("lost-sight asker started")
    return dialog, th


def _build_vision(cfg, camera, store, bus):
    """Load the models and build the VisionLoop (R11.12). Returns (loop, hands) or raises."""
    from lastseen.capture.ringbuffer import RingBuffer
    from lastseen.engine.touch import TouchWatcher
    from lastseen.engine.vision_loop import VisionLoop
    from lastseen.engine.zones import ZoneMap
    from lastseen.vision.change import ChangeDetector
    from lastseen.vision.classify import ItemClassifier
    from lastseen.vision.detector import Detector
    from lastseen.vision.embedder import ClipEmbedder
    from lastseen.vision.hands import HandDetector
    from lastseen.vision.identity import Identity

    models = Path(cfg.paths.models)
    detector = Detector(cfg)
    detector.set_items(cfg.enabled_items())
    wearable = cfg.camera.mode == "wearable"
    embedder = ClipEmbedder(cfg.device, models, cfg.identity.crop_pad)
    hands = HandDetector(str(models / "hand_landmarker.task"))
    people = None if wearable else _make_people(cfg)
    change = ChangeDetector()  # built for VisionLoop's signature; nothing calls it in wearable mode
    classifier = touch = None
    if not wearable:
        try:
            classifier = ItemClassifier(embedder, cfg.items)
            touch = TouchWatcher(change, cfg.engine)
        except Exception:
            log.exception("item classifier failed to load; touch-to-track off")
    zones = ZoneMap([]) if wearable else ZoneMap.load("zones.json")
    loop = VisionLoop(cfg, camera, RingBuffer(), store, bus, zones, detector, hands,
                      embedder, change, Path(cfg.paths.data) / "clips",
                      identity=Identity(embedder, cfg.identity), people=people,
                      classifier=classifier, touch=touch)
    return loop, hands


def main() -> int:
    cfg = load_config(os.environ.get("LASTSEEN_CONFIG", "config.yaml"))
    logfile = setup_logging(cfg.paths.data)
    log.info("started (device=%s, items=%s, log=%s)", cfg.device, [i.id for i in cfg.items], logfile)

    import uvicorn

    from lastseen.bus import Bus
    from lastseen.capture.camera import LatestFrameCamera
    from lastseen.memory.store import Store
    from lastseen.server.app import AppContext, create_app

    bus = Bus()
    store = Store(str(Path(cfg.paths.data) / "lastseen.db"), bus, cfg.engine.uncertain_conf)
    camera = LatestFrameCamera(cfg.camera.source, cfg.camera.width, cfg.camera.replay_video)
    started = False
    fake = None
    loop = hands = None
    cleanup_stop = threading.Event()
    speaker = listener = None
    asker_stop = threading.Event()
    asker_thread = None
    wearable = cfg.camera.mode == "wearable"
    try:
        camera.start()
        started = True
        threading.Thread(target=_cleanup_loop, args=(Path(cfg.paths.data) / "clips", cleanup_stop),
                         name="clip-cleanup", daemon=True).start()
        if cfg.features.fake_tracker:
            from lastseen.engine.fake import FakeTracker

            name = next((i.display_name for i in cfg.items if i.id == "airpods"), "AirPods")
            fake = FakeTracker(store, bus, camera, Path(cfg.paths.data) / "clips",
                               display_name=name)
            fake.start()
            log.info("fake tracker started")
        else:
            try:
                loop, hands = _build_vision(cfg, camera, store, bus)
                loop.start()
                log.info("vision loop started")
            except Exception:
                log.exception("vision loop failed to start; serving without vision")
                loop = None
        ctx = AppContext(cfg=cfg, bus=bus, store=store, camera=camera)
        from lastseen.brain.answer import AnswerEngine
        from lastseen.engine.zones import ZoneMap

        from lastseen.brain.llm import ChalkLLM

        llm = ChalkLLM.from_env()
        if llm is None:
            log.info("chalk: off (no credentials)")
        else:
            log.info("chalk: on (%s, %s)", llm.host, llm.model)
            llm.on_status = lambda s: ctx.metrics.__setitem__("chalk", s)
        if loop is not None:
            zones = loop.zones
        else:
            zones = ZoneMap([]) if wearable else ZoneMap.load("zones.json")
        engine = AnswerEngine(cfg, store, zones,
                              llm=llm, bus=bus, frame_wh=loop.frame_wh if loop is not None else None,
                              enroll_fn=loop.start_enroll if loop is not None and not wearable else None)
        ctx.ask_fn = engine.ask
        ctx.metrics["chalk"] = "off" if llm is None else None
        if loop is not None:
            loop.metrics["chalk"] = ctx.metrics.get("chalk")
            ctx.metrics = loop.metrics
            ctx.overlay_fn = loop.overlay

            def enroll_fn(item_id, display_name, prompt=None, x=None, y=None):
                if x is not None and y is not None:
                    return loop.click_enroll(item_id, display_name, x, y)
                return loop.start_enroll(item_id, display_name, prompt)

            ctx.enroll_fn = enroll_fn
            ctx.forget_fn = loop.forget
        if cfg.features.voice:
            try:
                from lastseen.voice.listen import Listener
                from lastseen.voice.route import make_on_text
                from lastseen.voice.speak import Speaker

                from lastseen.voice.grok_tts import GrokTTS
                from lastseen.voice.settings import VoiceSettings

                tts = GrokTTS.from_env()
                log.info("grok voices: %s", "on" if tts is not None else "off (no XAI_API_KEY)")
                speaker = Speaker(tts=tts)
                ctx.voice_settings = VoiceSettings(speaker, tts, Path(cfg.paths.data) / "settings.json")
                log.info("voice: %s", speaker.voice)

                dialog, asker_thread = _start_asker(cfg, loop, speaker, engine, bus, asker_stop, ctx)

                on_text = make_on_text(engine, speaker, cfg.items, dialog=dialog)

                listener = Listener(on_text, speaker.speaking, models_dir=str(Path(cfg.paths.models) / "whisper"),
                                    on_status=lambda s: ctx.metrics.__setitem__("mic", s),
                                    muted_until=speaker.muted_until)
                ctx.metrics["mic"] = listener.status
                listener.start()
            except Exception:
                log.exception("voice failed to start")
                ctx.metrics["mic"] = "off: failed to start"
        app = create_app(ctx)
        port = int(os.environ.get("LASTSEEN_PORT", cfg.server.port))
        log.info("serving on http://localhost:%d/dashboard (wall frame: http://<laptop-ip>:%d/frame; "
                 "dashboard %s)", port, port, "open to the LAN" if cfg.server.lan_dashboard else "local-only")
        # /stream (MJPEG) responses never finish on their own, so uvicorn's graceful shutdown
        # waited on them forever after Ctrl+C. handle_exit ends them; the timeout is a backstop.
        server = uvicorn.Server(server_config(app, port))
        uvicorn_exit = server.handle_exit

        def handle_exit(sig, frame):  # end /stream and /ws loops first, then let uvicorn stop
            ctx.stopping.set()
            uvicorn_exit(sig, frame)

        server.handle_exit = handle_exit
        try:
            server.run()
        except KeyboardInterrupt:  # uvicorn re-raises the captured SIGINT after shutting down
            pass
    finally:
        cleanup_stop.set()
        asker_stop.set()
        if asker_thread is not None:
            asker_thread.join(timeout=2)
        if listener is not None:
            listener.stop()
        if speaker is not None:
            speaker.stop()
        if fake is not None:
            fake.stop()
        if loop is not None:
            loop.stop()
        if hands is not None:
            hands.close()
        if started:
            camera.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
