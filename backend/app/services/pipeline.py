"""检测流水线：采集 → 推理 → 事件落库 → WebSocket 广播 → 报警引擎 → 外联动。

架构直接迁移自 Frigate（MIT）的帧源/检测/事件分层与 HIKONCam 的
"采集与处理解耦、界面不阻塞吞吐"原则：
- 采集线程（本类 _run）只做取帧/推理/落库/广播；
- 界面（Web HMI / PyQt5 桌面壳）通过 WebSocket 被动消费，卡顿不影响检测；
- 一"件"（卷）= 一次 start→stop 周期，缺陷/耗时按卷统计（对齐 HIKONCam 单件口径）；
- 报警触发后经 services/linkage.py 外发 PLC/Modbus（写失败不阻塞检测线程）。
"""
from __future__ import annotations

import base64
import threading
import time

import cv2

from ..core.config import settings
from ..db import FRAME_DIR, SessionLocal
from ..models import Coil, Defect
from .detector import Detector
from .source import FrameSource

_GREEN = (34, 197, 94)  # BGR：算法监测统一绿色框（与 HMI 叠加层同视觉语言）


def _paint(frame, dets, names):
    """证据帧标注：绿框 + 类别/置信度标签。实况画面不在此绘制——
    实时框由前端矢量叠加（清晰、可显数值、随帧变动不增加编码负担）。"""
    img = frame.copy()
    for d in dets:
        color = _GREEN
        x1, y1, x2, y2 = (int(v) for v in d.xyxy)
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        label = f"{names.get(d.cls_id, d.cls_id)} {d.conf:.2f}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(img, (x1, max(0, y1 - th - 8)),
                      (x1 + tw + 6, y1), color, -1)
        cv2.putText(img, label, (x1 + 3, max(12, y1 - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (12, 16, 24), 1, cv2.LINE_AA)
    return img


def _save_jpeg(img, path: str) -> None:
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if ok:
        buf.tofile(path)  # 兼容中文路径（cv2.imwrite 在 Windows 非 ASCII 路径下会失败）


class Pipeline:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = False
        self._broadcast = None
        self.state = {
            "running": False, "coil_id": None, "coil_no": "",
            "frame_idx": 0, "source": "", "last_error": "",
            "model": "", "backend": "", "provider": "",
            "tiling": False,
        }

    def attach_broadcast(self, fn) -> None:
        self._broadcast = fn

    def status(self) -> dict:
        return dict(self.state)

    def _send(self, payload: dict) -> None:
        if self._broadcast:
            self._broadcast(payload)

    def start(self, source: str = "", coil_no: str = "") -> dict:
        cfg = settings.get()
        if self.state["running"]:
            raise RuntimeError("已有检测卷正在运行，请先『结束本卷』")
        src_path = (source or cfg.get("source_path") or "").strip()
        camera = cfg.get("camera") or {}
        frame_src = FrameSource(src_path, fps=float(cfg.get("fps", 10)),
                                camera_cfg=camera)
        det = Detector(cfg.get("model_path", ""),
                       conf=float(cfg.get("conf", 0.25)),
                       iou=float(cfg.get("iou", 0.45)),
                       class_names=cfg.get("class_names"),
                       providers=cfg.get("infer_providers", "auto"),
                       fp16=bool(cfg.get("fp16", False)),
                       tiling=cfg.get("tiling"))
        no = coil_no.strip() or time.strftime("C%Y%m%d-%H%M%S")
        with SessionLocal() as db:
            coil = Coil(coil_no=no, source=src_path, status="running")
            db.add(coil)
            db.commit()
            db.refresh(coil)
            coil_id = coil.id
        self._stop = False
        self.state.update(running=True, coil_id=coil_id, coil_no=no,
                          frame_idx=0, source=src_path, last_error="",
                          model=det.name, backend=det.backend,
                          provider=det.provider, tiling=bool(
                              det.tiling.get("enabled")))
        self._thread = threading.Thread(
            target=self._run, args=(frame_src, det, coil_id, no, cfg),
            daemon=True)
        self._thread.start()
        return self.status()

    def stop(self) -> dict:
        self._stop = True
        return self.status()

    # ---------------------------------------------------------------- 工作线程
    def _run(self, src: FrameSource, det: Detector, coil_id: int,
             coil_no: str, cfg: dict) -> None:
        from . import alarms
        from .linkage import linkage

        fps = max(float(cfg.get("fps", 10)), 1.0)
        ev_conf = float(cfg.get("evidence_conf", 0.5))
        mpf = float(cfg.get("meters_per_frame", 0.3))
        n = 0
        try:
            while not self._stop:
                t0 = time.perf_counter()
                frame, _ = src.read()
                if frame is None:
                    break
                n += 1
                dets = det.infer(frame)
                events: list[dict] = []
                with SessionLocal() as db:
                    coil = db.get(Coil, coil_id)
                    for k, d in enumerate(dets):
                        path = ""
                        if d.conf >= ev_conf:
                            # 证据帧：整帧标注（保留上下文，便于人工复核与审计）
                            fname = FRAME_DIR / f"coil{coil_id}_{n}_{k}.jpg"
                            _save_jpeg(_paint(frame, [d], det.names), str(fname))
                            path = str(fname)
                        row = Defect(
                            coil_id=coil_id, frame_idx=n, class_id=d.cls_id,
                            cls_name=det.names.get(d.cls_id, str(d.cls_id)),
                            conf=round(d.conf, 4),
                            x1=round(d.xyxy[0], 1), y1=round(d.xyxy[1], 1),
                            x2=round(d.xyxy[2], 1), y2=round(d.xyxy[3], 1),
                            evidence_path=path)
                        db.add(row)
                        db.flush()
                        events.append({
                            "id": row.id, "ts": row.ts, "cls": row.cls_name,
                            "conf": row.conf, "x1": row.x1, "y1": row.y1,
                            "x2": row.x2, "y2": row.y2,
                        })
                        for a in alarms.eval_defect_alarm(db, coil, row, cfg):
                            self._send({"type": "alarm", "alarm": a})
                            linkage.notify(cfg, a)
                    total = db.query(Defect).filter(
                        Defect.coil_id == coil_id).count()
                    coil.defect_count = total
                    coil.frames_total = n
                    coil.length_m = round(n * mpf, 2)
                    db.commit()
                ok, buf = cv2.imencode(".jpg", frame,
                                       [int(cv2.IMWRITE_JPEG_QUALITY), 70])
                if ok:
                    self._send({
                        "type": "frame",
                        "jpeg": base64.b64encode(buf.tobytes()).decode(),
                        "coil_id": coil_id, "coil_no": coil_no,
                        "frame_idx": n, "defect_count": total,
                        "w": frame.shape[1], "h": frame.shape[0],
                        "events": events,
                    })
                self.state["frame_idx"] = n
                rest = 1.0 / fps - (time.perf_counter() - t0)
                if rest > 0:
                    time.sleep(rest)
        except Exception as exc:  # 线程内异常上报，避免静默失败
            self.state["last_error"] = f"{type(exc).__name__}: {exc}"
        finally:
            src.release()
            self._finish(coil_id, coil_no, n, cfg)

    def _finish(self, coil_id: int, coil_no: str, n: int, cfg: dict) -> None:
        from . import alarms, reports
        from .linkage import linkage

        grade = ""
        with SessionLocal() as db:
            coil = db.get(Coil, coil_id)
            if coil is None:
                return
            coil.end_ts = time.strftime("%Y-%m-%d %H:%M:%S")
            coil.status = "closed"
            coil.frames_total = n
            coil.length_m = round(n * float(cfg.get("meters_per_frame", 0.3)), 2)
            coil.defect_count = db.query(Defect).filter(
                Defect.coil_id == coil_id).count()
            db.commit()
            rep = reports.coil_report(db, coil_id, cfg)
            if rep:
                grade = rep["grade"]
                coil.quality_grade = grade
                db.commit()
                if grade == "C":
                    a = alarms.raise_alarm(
                        db, coil_id, "grade", "critical",
                        f"卷 {coil_no} 判定等级 C：缺陷密度 {rep['density_per_m']} 个/米")
                    if a:
                        self._send({"type": "alarm", "alarm": a})
                        linkage.notify(cfg, a)
        self.state["running"] = False
        self._send({"type": "coil_closed", "coil_id": coil_id,
                    "coil_no": coil_no, "grade": grade})


pipeline = Pipeline()
