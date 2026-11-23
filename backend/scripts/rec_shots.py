"""录屏效果预览：浅色主题下逐页实拍（含运行中监控画面，真实帧 + 检测框）。

用法：py -3.12 scripts/rec_shots.py
产物：scripts/shots/rec-{review,reports,alarms,settings,dashboard-live}.png
说明：实拍前先跑 demo_coil.py + review_demo.py，让报表/复核/报警页有完整数据。
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
SHOTS = "scripts/shots"
NEU_SOURCE = r"D:\横向项目\steel-surface-defect\datasets\processed\neu_det\images\test"


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
    token = http("/api/auth/login", "POST",
                 payload={"username": "admin", "password": "admin123"})["token"]
    shots: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1680, "height": 960})
        page.goto(f"{BASE}/dashboard", wait_until="networkidle")
        page.evaluate(f"localStorage.setItem('sv_token', {token!r})")
        page.reload(wait_until="networkidle")

        theme = page.evaluate("document.documentElement.dataset.theme")
        print(f"默认主题: {theme}")

        # 静态页先拍（此时最新卷 = 已复核的 DEMO 卷，各页默认选中它）
        for name, path, wait_ms in [
            ("review", "/review", 1200),
            ("reports", "/reports", 2000),
            ("alarms", "/alarms", 1000),
            ("settings", "/settings", 1000),
        ]:
            page.goto(f"{BASE}{path}", wait_until="networkidle")
            page.wait_for_timeout(wait_ms)
            f = f"{SHOTS}/rec-{name}.png"
            page.screenshot(path=f)
            shots.append(f)
            print(f"已截图 {f}")

        # 运行中监控页（真实帧 + 绿色检测框 + 事件流）
        coil_no = time.strftime("PREVIEW-%m%d-%H%M%S")
        http("/api/pipeline/start", "POST", token,
             {"coil_no": coil_no, "source": NEU_SOURCE})
        page.goto(f"{BASE}/dashboard", wait_until="networkidle")
        try:
            page.wait_for_selector(".canvas-stage img", timeout=30000)
            page.wait_for_timeout(7000)  # 攒几行事件流再拍
        except Exception:
            print("未等到实时画面，按当前状态截图")
        f = f"{SHOTS}/rec-dashboard-live.png"
        page.screenshot(path=f)
        shots.append(f)
        print(f"已截图 {f}（运行卷 {coil_no}）")

        http("/api/pipeline/stop", "POST", token)
        for _ in range(30):
            time.sleep(1)
            if not http("/api/system/status")["pipeline"]["running"]:
                break
        browser.close()

    print("完成:", ", ".join(shots))
    return 0


if __name__ == "__main__":
    sys.exit(main())
