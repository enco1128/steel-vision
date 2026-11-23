"""HMI 绿框实时叠加验证：启动一卷 → 核验 WS 帧载荷 → 截图监控页 → 结束卷。

检查项：
1. WS frame 消息携带 w/h 帧尺寸与 events 检测框（前端矢量叠加依据）；
2. 截图确认画面中绿色检测框与类别/置信度标签确实渲染；
3. 结束后清理，不影响既有演示数据（本次验证卷独立成卷）。

用法：
    python scripts/verify_hmi.py                     # 默认 NEU 测试集 20 秒
    python scripts/verify_hmi.py --seconds 30 --shot shots/dashboard.png
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright
import websocket  # websocket-client

BASE = "http://127.0.0.1:8000"
WS_URL = "ws://127.0.0.1:8000/ws"
REPO = Path(__file__).resolve().parents[2]          # steel-vision/
DEFAULT_SOURCE = str(Path(os.environ.get(
    "SV_DEMO_SOURCE",
    REPO.parent / "steel-surface-defect" / "datasets" / "processed"
    / "neu_det" / "images" / "test")))


def http(path: str, method: str = "GET", token: str = "",
         payload: dict | None = None, timeout: float = 30) -> dict:
    req = urllib.request.Request(BASE + path, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if method in ("POST", "PUT"):
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description="HMI 绿框叠加验证")
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--source", default=DEFAULT_SOURCE)
    ap.add_argument("--shot", default="shots/dashboard-green-box.png")
    args = ap.parse_args()

    token = http("/api/auth/login", "POST",
                 payload={"username": "admin", "password": "admin123"})["token"]

    # 1) WS 探针：后台收集帧载荷样本
    frames: list[dict] = []
    stop_flag = threading.Event()

    def on_msg(ws, msg):
        if len(frames) >= 400:
            return
        try:
            m = json.loads(msg)
        except Exception:
            return
        if m.get("type") == "frame":
            frames.append({
                "w": m.get("w"), "h": m.get("h"),
                "n_events": len(m.get("events") or []),
                "events": (m.get("events") or [])[:3],
                "jpeg_len": len(m.get("jpeg") or ""),
            })

    def ws_thread():
        ws = websocket.WebSocketApp(WS_URL, on_message=on_msg)
        ws.run_forever()

    threading.Thread(target=ws_thread, daemon=True).start()
    time.sleep(1)

    # 2) 启动验证卷
    coil_no = time.strftime("HMI-VERIFY-%H%M%S")
    http("/api/pipeline/start", "POST", token,
         {"coil_no": coil_no, "source": args.source})

    # 3) 等画面有框后截图
    deadline = time.time() + args.seconds
    shot_taken = False
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1680, "height": 960})
        page.goto(f"{BASE}/dashboard", wait_until="networkidle")
        while time.time() < deadline:
            time.sleep(2)
            boxes = page.locator("svg.det-overlay rect.det-box").count()
            print(f"  t={int(time.time() - (deadline - args.seconds))}s "
                  f"页面绿框数={boxes} ws帧样本={len(frames)}")
            if boxes > 0 and not shot_taken:
                time.sleep(1.2)  # 让标签渲染稳定
                page.screenshot(path=args.shot)
                shot_taken = True
                print(f"  已截图: {args.shot}")
                break
        if not shot_taken:
            page.screenshot(path=args.shot)
            print(f"  未捕获到绿框，仍截图现场: {args.shot}")
        browser.close()

    # 4) 结束卷并核验载荷
    http("/api/pipeline/stop", "POST", token)
    for _ in range(20):
        time.sleep(2)
        if not http("/api/system/status")["pipeline"]["running"]:
            break

    with_boxes = [f for f in frames if f["n_events"] > 0]
    sized = [f for f in frames if f["w"] and f["h"]]
    print("\n===== WS 帧载荷核验 =====")
    print(f"帧样本 {len(frames)} | 带帧尺寸 {len(sized)} | 带检测框 {len(with_boxes)}")
    if with_boxes:
        ex = with_boxes[-1]
        print(f"样例: w={ex['w']} h={ex['h']} events={ex['n_events']}")
        for e in ex["events"]:
            print(f"  box {e['cls']} conf={e['conf']} "
                  f"x1={e['x1']} y1={e['y1']} x2={e['x2']} y2={e['y2']}")
    ok = bool(sized and with_boxes and shot_taken)
    print(f"\n核验结论: {'PASS' if ok else 'CHECK'}（截图 {args.shot}）")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
