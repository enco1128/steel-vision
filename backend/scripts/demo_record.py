"""自动演示录屏：Playwright 真实操作一遍业务故事线，录成 webm（无浏览器边框）。

用法：py -3.12 scripts/demo_record.py
产物：docs/rec/demo-full.webm（1280x720）
后续：video_to_gif.py 转 GIF → insert_ppt.py 插入 PPT 第 11 页。
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
REC_DIR = Path(r"d:\横向项目\steel-vision\docs\rec")
TMP_DIR = REC_DIR / "_tmp"
STORY_COIL = "DEMO-1115-224116"   # 故事线完整的演示卷（89 确认 / 84 误报 / 判级 B）


def http(path: str, method: str = "GET", token: str = "",
         payload: dict | None = None) -> dict:
    req = urllib.request.Request(BASE + path, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if method in ("POST", "PUT"):
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _select_by_text(page, select_locator, fragment: str) -> bool:
    """把 <select> 切到 option 文本包含 fragment 的那一项。"""
    return page.evaluate(
        """([frag]) => {
            const sels = [...document.querySelectorAll('select')];
            for (const s of sels) {
                const opt = [...s.options].find(o => o.textContent.includes(frag));
                if (opt) { s.value = opt.value;
                           s.dispatchEvent(new Event('change', {bubbles: true}));
                           return true; }
            }
            return false;
        }""", [fragment])


def main() -> int:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    token = http("/api/auth/login", "POST",
                 payload={"username": "admin", "password": "admin123"})["token"]
    coil_no = time.strftime("B2606-%m%d-%H%M%S")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir=str(TMP_DIR),
            record_video_size={"width": 1280, "height": 720})
        page = ctx.new_page()
        page.goto(f"{BASE}/dashboard", wait_until="networkidle")
        page.evaluate(f"localStorage.setItem('sv_token', {token!r})")
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(1500)  # 待命态定格

        # 1) 填写卷号 + 选 NEU 样本目录，点击开始检测
        page.locator("input.input").first.fill(coil_no)
        _select_by_text(page, page.locator("select").first, "neu_det")
        page.get_by_role("button", name="开始检测").click()

        # 2) 实时画面：绿框 + 事件流；报警横幅弹出即确认（ISA-18.2 ack 演示）
        page.wait_for_timeout(4200)
        banner_ack = page.locator(".alarm-banner button")
        if banner_ack.count() > 0:
            banner_ack.first.click()
            page.wait_for_timeout(400)
        page.wait_for_timeout(3600)

        # 3) 复核页：证据帧弹窗 → 标记误报（表内标签即时变化）
        page.goto(f"{BASE}/review", wait_until="networkidle")
        page.wait_for_timeout(1300)
        page.get_by_role("button", name="证据帧").first.click()
        page.wait_for_timeout(2300)
        page.get_by_role("button", name="标记误报").click()
        page.wait_for_timeout(1300)

        # 4) 报表页：切到故事线卷，展示判级 B / 密度 1.84 / 类别分布
        page.goto(f"{BASE}/reports", wait_until="networkidle")
        page.wait_for_timeout(900)
        _select_by_text(page, page.locator("select").first, STORY_COIL)
        page.wait_for_timeout(3000)

        # 5) 报警页：确认一条未确认报警
        page.goto(f"{BASE}/alarms", wait_until="networkidle")
        page.wait_for_timeout(1100)
        ack_btn = page.get_by_role("button", name="确认报警")
        if ack_btn.count() > 0:
            ack_btn.first.click()
            page.wait_for_timeout(1100)

        # 6) 回监控页结束本卷；随后演示深浅主题切换
        page.goto(f"{BASE}/dashboard", wait_until="networkidle")
        page.wait_for_timeout(700)
        page.get_by_role("button", name="结束本卷").click()
        page.wait_for_timeout(1500)
        page.get_by_role("button", name="深色").click()
        page.wait_for_timeout(2300)
        page.get_by_role("button", name="浅色").click()
        page.wait_for_timeout(1200)

        video = page.video
        ctx.close()
        browser.close()
        src = Path(video.path()) if video else next(TMP_DIR.glob("*.webm"), None)

    if not src or not src.exists():
        print("未生成录屏文件")
        return 1
    dst = REC_DIR / "demo-full.webm"
    if dst.exists():
        dst.unlink()
    src.replace(dst)
    size_mb = dst.stat().st_size / 1024 / 1024
    print(f"录屏完成: {dst}（{size_mb:.1f} MB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
