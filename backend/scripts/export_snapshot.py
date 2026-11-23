# -*- coding: utf-8 -*-
"""从运行中的 SteelVision 导出去敏演示快照（供 GitHub Pages 静态演示）。

产物：frontend/public/demo/snapshot.json
    { coils, defects, alarms, settings, model_info,
      frames: [dataURL...], frame_meta: {w,h,coil_no,defect_count,events_by_idx},
      evidence: {defect_id: dataURL} }

用法：后端运行中执行
    py -3.12 scripts/export_snapshot.py                # 用 DEMO 故事线卷
    py -3.12 scripts/export_snapshot.py --coil DEMO-1115-224116
    py -3.12 scripts/export_snapshot.py --frames 40    # 帧序列长度
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
REPO = Path(__file__).resolve().parents[2]          # steel-vision/
OUT = REPO / "frontend" / "public" / "demo" / "snapshot.json"


def http(path, method="GET", token="", payload=None, timeout=60):
    req = urllib.request.Request(BASE + path, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if method == "POST":
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(payload or {}).encode()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        ct = r.headers.get("content-type", "")
        return json.loads(raw) if "json" in ct else raw


def login():
    return http("/api/auth/login", "POST",
                payload={"username": "admin", "password": "admin123"})["token"]


def evidence_dataurl(defect_id: int, token: str) -> str:
    """证据帧转 480px 宽 JPEG dataURL（演示样本帧，不含甲方任何现场数据）。"""
    try:
        raw = http(f"/api/evidence/{defect_id}", token=token)
    except Exception:
        return ""
    try:
        import cv2
        import numpy as np
        arr = np.frombuffer(raw, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return ""
        h, w = img.shape[:2]
        tw = 480
        img = cv2.resize(img, (tw, int(h * tw / w)))
        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 72])
        return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()
    except Exception:
        return "data:image/jpeg;base64," + base64.b64encode(raw).decode()


def ok_png_dataurl(path: str, tw: int = 640) -> str:
    try:
        import cv2
        data = cv2.imdecode(  # 支持中文路径
            __import__("numpy").fromfile(path, dtype=__import__("numpy").uint8),
            cv2.IMREAD_COLOR)
        if data is None:
            return ""
        h, w = data.shape[:2]
        data = cv2.resize(data, (tw, int(h * tw / w)))
        ok, buf = cv2.imencode(".jpg", data, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
        if not ok:
            return ""
        return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()
    except Exception:
        return ""


def capture_frames(seconds: float, source: str = "") -> list:
    """启动一卷检测（默认合成帧，可指定图像目录），采集实时 JPEG 帧与事件。"""
    import websocket  # websocket-client
    token = login()
    try:
        http("/api/pipeline/stop", "POST", token)   # 清理可能残留的运行卷
    except Exception:
        pass
    time.sleep(1)
    live_no = time.strftime("DEMO-LIVE-%H%M%S")     # 唯一卷号，避免约束冲突
    # 临时下调 conf 让演示帧检测框更密集（采完恢复）
    try:
        orig_settings = http("/api/settings", token=token)
        http("/api/settings", "PUT", token, {**orig_settings, "conf": 0.10})
    except Exception:
        orig_settings = None
    frames, events_by_idx = [], []
    collected = {"n": 0}
    ws = websocket.create_connection("ws://127.0.0.1:8000/ws", timeout=10)
    meta = {"w": 960, "h": 540}
    try:
        http("/api/pipeline/start", "POST", token,
             {"coil_no": live_no, "source": source})
        t0 = time.time()
        while time.time() - t0 < seconds:
            try:
                msg = json.loads(ws.recv())
            except Exception:
                break
            if msg.get("type") == "frame":
                frames.append("data:image/jpeg;base64," + msg["jpeg"])
                evs = [{"id": e["id"], "ts": e["ts"], "cls": e["cls"],
                        "conf": e["conf"], "x1": e["x1"], "y1": e["y1"],
                        "x2": e["x2"], "y2": e["y2"]} for e in msg.get("events", [])]
                events_by_idx.append(evs)
                collected["n"] += 1
                meta = {"w": msg.get("w", 960), "h": msg.get("h", 540)}
                if len(frames) >= 60:
                    break
            elif msg.get("type") == "coil_closed":
                break
    finally:
        try:
            http("/api/pipeline/stop", "POST", token)
        except Exception:
            pass
        ws.close()
        if orig_settings is not None:
            try:
                http("/api/settings", "PUT", token, orig_settings)   # 恢复原阈值
            except Exception:
                pass
    time.sleep(0.5)
    meta.update({"coil_no": live_no, "defect_count": collected["n"]})
    return frames, events_by_idx, meta


def main() -> int:
    ap = argparse.ArgumentParser(description="导出静态演示快照")
    ap.add_argument("--coil", default="", help="演示卷号（默认自动选缺陷最多的 DEMO 卷）")
    ap.add_argument("--frames", type=float, default=6.0, help="实时帧采集秒数")
    ap.add_argument("--source", default="", help="采集帧用数据源（图像目录/视频，默认合成帧）")
    ap.add_argument("--no-frames", action="store_true", help="跳过实时帧采集")
    args = ap.parse_args()

    token = login()
    coils = http("/api/coils", token=token)
    # 剔除历史临时/自检卷与采集专用 LIVE 卷，只保留演示价值高的卷
    KEEP_PREFIX = ("DEMO-", "B2606-", "SOAK-1115-2036-001")
    coils = [c for c in coils if c["coil_no"].startswith(KEEP_PREFIX)
             and not c["coil_no"].startswith("DEMO-LIVE")]
    # 优先 173 缺陷的故事线卷
    story = None
    if args.coil:
        story = next((c for c in coils if c["coil_no"] == args.coil), None)
    else:
        demo = [c for c in coils if c["coil_no"].startswith("DEMO")]
        demo.sort(key=lambda c: c["defect_count"], reverse=True)
        story = demo[0] if demo else (coils[0] if coils else None)
    if not story:
        print("没有可用卷数据", file=sys.stderr)
        return 1
    # 故事线卷置顶（演示页面默认选中）
    coils.sort(key=lambda c: (c["id"] != story["id"], -c["id"]))

    defects = http(f"/api/coils/{story['id']}/defects", token=token)

    # 证据帧：仅取“演示样本”标注帧，限量 24 张控制体积
    evidence = {}
    for d in defects[:24]:
        if d.get("evidence_path"):
            try:
                url = evidence_dataurl(d["id"], token)
                if url:
                    evidence[d["id"]] = url
            except Exception:
                pass

    alarms = http("/api/alarms?limit=80", token=token)
    settings = http("/api/settings", token=token)
    model_info = http("/api/model/info", token=token)

    # 去敏：模型/数据源路径不外泄
    settings = {**settings, "model_path": "(演示快照)",
                "source_path": "(演示快照)"}
    model_info = {**model_info, "model_path": "(演示快照)",
                  "available_providers": model_info.get("available_providers", []),
                  "camera_adapters": model_info.get("camera_adapters", [])}

    frames, events_by_idx, fmeta = ([], [], {"w": 960, "h": 540, "coil_no": story["coil_no"],
                                             "defect_count": story["defect_count"]})
    if not args.no_frames:
        try:
            frames, events_by_idx, fmeta = capture_frames(args.frames, args.source)
        except Exception as exc:
            import traceback
            print(f"实时帧采集跳过：{exc}", file=sys.stderr)
            traceback.print_exc()
        fmeta["coil_no"] = story["coil_no"]
        fmeta["defect_count"] = story["defect_count"]

    snap = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "coils": coils,
        "defects": defects,
        "alarms": alarms,
        "settings": settings,
        "model_info": model_info,
        "frames": frames,
        "frame_meta": {**fmeta, "events_by_idx": events_by_idx},
        "evidence": evidence,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    mb = OUT.stat().st_size / 1024 / 1024
    print(f"已导出: {OUT}  ({mb:.2f} MB)")
    print(f"  卷 {len(coils)} · 缺陷 {len(defects)} · 报警 {len(alarms)} · "
          f"帧 {len(frames)} · 证据帧 {len(evidence)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
