"""系统配置：默认值 + config.json 持久化（阈值/报警/推理后端/切片/相机/联动）。"""
from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.json"
WORKSPACE = Path(__file__).resolve().parents[4]  # d:\横向项目

DEFAULTS: dict = {
    "model_path": str(WORKSPACE / "steel-surface-defect" / "runs" / "train"
                      / "yolo11s_neu_det" / "weights" / "best.pt"),
    "source_path": "",
    "class_names": ["crazing", "inclusion", "patches", "pitted surface",
                    "rolled-in scale", "scratches"],
    "conf": 0.25,
    "iou": 0.45,
    "fps": 10,
    "evidence_conf": 0.5,
    "meters_per_frame": 0.3,
    "infer_providers": "auto",            # auto / tensorrt / cuda / cpu
    "fp16": False,
    "tiling": {"enabled": True, "tile_size": 1024, "overlap": 0.1,
               "trigger_min_side": 1280},
    "camera": {"enabled": False, "adapter": "opencv", "index": 0, "serial": ""},
    "alarms": {
        "min_defects_per_coil": 8,
        "density_per_m": 2.0,
        "priority_classes": ["inclusion", "rolled-in scale"],
    },
    "linkage": {
        "enabled": False,
        "driver": "dryrun",               # dryrun / snap7 / modbus
        "host": "192.168.2.1",
        "rack": 0,
        "slot": 1,
        "db": 1,
        "byte": 8080,                     # 对齐 HIKONCam：DB1.DBX8080.0
        "bit": 0,
        "pulse_ms": 500,
        "modbus_port": 502,
        "modbus_coil": 0,
    },
    "auth_enabled": True,
    "retention": {"evidence_days": 30},
}


class Settings:
    def __init__(self) -> None:
        self._lock = Lock()
        self._data: dict = json.loads(json.dumps(DEFAULTS))
        if CONFIG_PATH.exists():
            try:
                self._merge(json.loads(CONFIG_PATH.read_text("utf-8")))
            except Exception:
                pass
        for env, key, cast in (("SV_MODEL", "model_path", str),
                               ("SV_SOURCE", "source_path", str),
                               ("SV_FPS", "fps", float), ("SV_CONF", "conf", float)):
            if os.environ.get(env):
                self._data[key] = cast(os.environ[env])

    def _merge(self, patch: dict) -> None:
        for key, value in patch.items():
            if key not in DEFAULTS or value is None:
                continue
            if isinstance(DEFAULTS.get(key), dict) and isinstance(value, dict):
                self._data[key] = {**DEFAULTS[key],
                                   **self._data.get(key, {}), **value}
            else:
                self._data[key] = value

    def get(self) -> dict:
        return json.loads(json.dumps(self._data))

    def update(self, patch: dict) -> dict:
        with self._lock:
            self._merge(patch)
            CONFIG_PATH.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2), "utf-8")
        return self.get()


settings = Settings()
