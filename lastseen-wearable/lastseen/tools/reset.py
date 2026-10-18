"""Clear items' states, events and asks. Keeps galleries and zones: python -m lastseen.tools.reset"""
from __future__ import annotations

from pathlib import Path

from lastseen.bus import Bus
from lastseen.config import load_config
from lastseen.memory.store import Store


def main() -> None:
    cfg = load_config()
    db = Path(cfg.paths.data) / "lastseen.db"
    Store(str(db), Bus(), cfg.engine.uncertain_conf).reset_states()
    print(f"reset: cleared events/asks and set item states to UNKNOWN in {db} (gallery untouched)")


if __name__ == "__main__":
    main()
