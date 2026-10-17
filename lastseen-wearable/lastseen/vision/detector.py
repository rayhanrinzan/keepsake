"""YOLO-World wrapper: proposes candidate boxes; identity decides which one is ours."""
from __future__ import annotations

from pathlib import Path

from lastseen.config import Config, ItemCfg
from lastseen.types import Box
from lastseen.vision.geometry import clamp_box


class Detector:
    def __init__(self, cfg: Config):
        import ultralytics.nn.text_model as text_model

        # Keep YOLO-World's CLIP text encoder in models/ instead of ./weights.
        text_model.WEIGHTS_DIR = Path(cfg.paths.models)
        from ultralytics import YOLOWorld

        self.cfg = cfg
        self.model = YOLOWorld(cfg.detector.model)
        self.model.to(cfg.device)
        self.class_items: list[str] = []

    def set_items(self, items: list[ItemCfg], generic_prompts: list[str] | None = None) -> None:
        generic = self.cfg.generic_prompts if generic_prompts is None else generic_prompts
        classes: list[str] = []
        mapping: list[str] = []
        for it in items:
            prompts = ([it.prompt] if it.prompt else []) + list(it.extra_prompts)
            for p in prompts:
                classes.append(p)
                mapping.append(it.id)
        for p in generic:
            classes.append(p)
            mapping.append("*")
        self.class_items = mapping
        self.model.set_classes(classes)

    def detect(self, frame) -> list[tuple[str, Box, float]]:
        d = self.cfg.detector
        r = self.model.predict(frame, conf=d.conf, imgsz=d.imgsz, device=self.cfg.device,
                               verbose=False)[0]
        h, w = frame.shape[:2]
        out = []
        for b in r.boxes:
            box = clamp_box(b.xyxy[0].tolist(), w, h)
            area = (box[2] - box[0]) * (box[3] - box[1])
            if area > d.max_area_frac * w * h:
                continue
            out.append((self.class_items[int(b.cls)], box, float(b.conf)))
        return out
