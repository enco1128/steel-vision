"""帧源：视频文件 / 图像目录 / 相机(适配层) / 合成帧。

kind 判定优先级：camera（设置页启用时）> 目录 > 文件 > 合成帧。
相机后端见 services/camera.py（opencv / hikrobot / pypylon 可插拔）。
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .camera import create as create_camera

_IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}


class FrameSource:
    def __init__(self, path: str = "", fps: float = 10.0, loop: bool = False,
                 camera_cfg: dict | None = None) -> None:
        self.fps = float(fps)
        self.loop = loop
        self.kind = "sample"
        self.cap = None
        self.files: list[Path] = []
        self.cam = None
        self.idx = 0

        cam = camera_cfg or {}
        if cam.get("enabled"):
            self.kind = "camera"
            kwargs = {k: v for k, v in cam.items()
                      if k not in ("enabled", "adapter")}
            self.cam = create_camera(cam.get("adapter", "opencv"), **kwargs)
            self.cam.open()
            return

        p = Path(path) if path else None
        if p and p.is_dir():
            self.kind = "images"
            self.files = sorted(x for x in p.rglob("*")
                                if x.suffix.lower() in _IMG_EXT)
            if not self.files:
                raise FileNotFoundError(f"目录内无图像文件: {path}")
            return

        if p and p.is_file():
            lower = p.name.lower()
            if lower.endswith((".mp4", ".avi", ".mkv", ".mov", ".wmv", ".m4v")):
                self.kind = "video"
                self.cap = cv2.VideoCapture(str(p))
                if not self.cap.isOpened():
                    raise FileNotFoundError(f"视频无法打开: {path}")
                return
            if p.suffix.lower() in _IMG_EXT:
                self.kind = "images"
                self.files = [p]
                return
            raise FileNotFoundError(f"不支持的数据源类型: {path}")

        if path:
            raise FileNotFoundError(f"数据源不存在: {path}")

    # ------------------------------------------------------------------
    @property
    def total(self) -> int:
        if self.kind == "images":
            return len(self.files)
        if self.kind == "video" and self.cap is not None:
            return int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        return -1

    def read(self):
        """返回 (frame, idx)；数据源结束时返回 (None, None)。"""
        if self.kind == "camera":
            frame = self.cam.read()
            if frame is None:
                return None, None
            self.idx += 1
            return frame, self.idx

        if self.kind == "images":
            if self.idx >= len(self.files):
                if not self.loop:
                    return None, None
                self.idx = 0
            data = np.fromfile(str(self.files[self.idx]), dtype=np.uint8)
            img = cv2.imdecode(data, cv2.IMREAD_COLOR)
            self.idx += 1
            if img is None:
                return self.read()  # 损坏文件跳过
            return img, self.idx

        if self.kind == "video":
            ok, frame = self.cap.read()
            if not ok:
                if self.loop:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    self.idx = 0
                    ok, frame = self.cap.read()
                if not ok:
                    return None, None
            self.idx += 1
            return frame, self.idx

        # sample：合成移动亮带，用于全链路冒烟（无相机/无样本时）
        w, h = 960, 540
        img = np.full((h, w, 3), 40, np.uint8)
        x = (self.idx * 7) % (w + 240) - 120
        cv2.rectangle(img, (x, 0), (x + 180, h), (92, 92, 92), -1)
        cv2.line(img, (0, h // 2), (w, h // 2), (120, 120, 120), 2)
        cv2.putText(img, f"SYNTHETIC FRAME {self.idx}", (20, 36),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (150, 150, 150), 2)
        self.idx += 1
        return img, self.idx

    def release(self) -> None:
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        if self.cam is not None:
            self.cam.release()
            self.cam = None
