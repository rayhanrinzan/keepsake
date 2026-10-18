"""Config loading and validation (pydantic v2)."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


def detect_device() -> Literal["mps", "cuda", "cpu"]:
    try:
        import torch  # lazy: keeps config loading cheap
    except ImportError:
        return "cpu"
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


class CameraCfg(BaseModel):
    source: int | str = 0
    width: int = 1280
    fps_target: float = Field(8, gt=0)
    replay_video: str | None = None
    mode: Literal["wearable", "fixed"] = "fixed"


class WearableCfg(BaseModel):
    ask_after_s: float = 30
    group_window_s: float = 10
    reply_window_s: float = 8
    touch_s: float = 0.5
    placed_hits: int = 3
    seen_again_hits: int = 3
    seen_again_window_s: float = 1.0
    stale_frame_s: float = 1.0
    best_frame_window_s: float = 5.0


class ItemCfg(BaseModel):
    id: str
    display_name: str
    prompt: str | None = None
    extra_prompts: list[str] = Field(default_factory=list)
    synonyms: list[str] = Field(default_factory=list)
    critical: bool = False
    enabled: bool = True


class DetectorCfg(BaseModel):
    conf: float = 0.001
    imgsz: int = 1280
    every_n: int = 3
    max_area_frac: float = 0.25
    model: str = "models/yolov8s-worldv2.pt"


class IdentityCfg(BaseModel):
    sim_thresh: float = 0.70
    margin_follow: float = 0.02
    margin_reacquire: float = 0.04
    reacquire_bonus: float = 0.05
    crop_pad: float = 0.15
    gallery_cap: int = 12


class EngineCfg(BaseModel):
    held_frames: int = 3
    placed_frames: int = 6
    missing_frames: int = 10
    still_px: int = 5
    move_px: int = 25
    near_hand_px: int = 150
    uncertain_conf: float = 0.6


class PersonsCfg(BaseModel):
    model: str = "models/yolo26n.pt"
    every_n: int = 2
    edge_frac: float = 0.03
    leave_after_s: float = 1.0


class FeaturesCfg(BaseModel):
    voice: bool = True
    memory_frame: bool = True
    chalk_llm: bool = True
    fake_tracker: bool = False
    search_sense: bool = False
    photon: bool = False
    clips: bool = True
    touch_to_track: bool = True
    people_tracking: bool = True  # person detector for "left the view"; off -> frame-edge fallback
    lost_sight_ask: bool = True


class PeopleCfg(BaseModel):
    user_name: str = "Mom"
    caregiver_name: str = "Anna"


class ServerCfg(BaseModel):
    port: int = 8000  # LASTSEEN_PORT overrides
    lan_dashboard: bool = False  # true: /dashboard, /stream, /health.html and POST /api/* open to the LAN


class DebugCfg(BaseModel):
    enroll_diagnostics: bool = False  # write an annotated jpg to data/clips when enrollment can't decide


class PathsCfg(BaseModel):
    data: str = "data"
    models: str = "models"


class Config(BaseModel):
    camera: CameraCfg = Field(default_factory=CameraCfg)
    items: list[ItemCfg]
    generic_prompts: list[str] = Field(default_factory=list)
    detector: DetectorCfg = Field(default_factory=DetectorCfg)
    identity: IdentityCfg = Field(default_factory=IdentityCfg)
    engine: EngineCfg = Field(default_factory=EngineCfg)
    persons: PersonsCfg = Field(default_factory=PersonsCfg)
    features: FeaturesCfg = Field(default_factory=FeaturesCfg)
    people: PeopleCfg = Field(default_factory=PeopleCfg)
    paths: PathsCfg = Field(default_factory=PathsCfg)
    server: ServerCfg = Field(default_factory=ServerCfg)
    debug: DebugCfg = Field(default_factory=DebugCfg)
    wearable: WearableCfg = Field(default_factory=WearableCfg)
    device: Literal["mps", "cuda", "cpu"] = "cpu"

    @model_validator(mode="before")
    @classmethod
    def _set_device(cls, data):
        if isinstance(data, dict) and "device" not in data:
            data = {**data, "device": detect_device()}
        return data

    def enabled_items(self) -> list[ItemCfg]:
        return [i for i in self.items if i.enabled]


def load_config(path: str | Path = "config.yaml") -> Config:
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    return Config.model_validate(raw)
