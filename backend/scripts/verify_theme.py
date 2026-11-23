"""界面规格验证：字号、浅色主题切换、合同号零残留、图表主题重绘。

用法：py -3.12 scripts/verify_theme.py
产物：scripts/shots/theme-{dark,light}-dashboard.png / theme-light-reports.png
"""
from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
SHOTS = "scripts/shots"


def main() -> int:
    results: dict[str, bool] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1680, "height": 960})
        page.goto(f"{BASE}/dashboard", wait_until="networkidle")
        page.wait_for_timeout(1500)

        body_fs = page.evaluate(
            "getComputedStyle(document.body).fontSize")
        title_fs = page.evaluate(
            "getComputedStyle(document.querySelector('.brand-title')).fontSize")
        content = page.locator("body").inner_text()
        results["字号 body=14px"] = body_fs == "14px"
        results["字号 brand-title=15px"] = title_fs == "15px"
        results["页面无合同号"] = "ACHXKT" not in content
        results["默认浅色主题"] = page.evaluate(
            "document.documentElement.dataset.theme") == "light"

        page.screenshot(path=f"{SHOTS}/theme-light-dashboard.png")

        # 切深色
        page.get_by_role("button", name="深色").click()
        page.wait_for_timeout(1200)
        results["切换后 data-theme=dark"] = page.evaluate(
            "document.documentElement.dataset.theme") == "dark"
        bg = page.evaluate(
            "getComputedStyle(document.body).backgroundColor")
        results["页面底色已变深"] = bg not in ("rgb(233, 235, 238)", "rgba(0, 0, 0, 0)")
        page.screenshot(path=f"{SHOTS}/theme-dark-dashboard.png")

        # 报表页（深色下图表应重绘为深底文字色）
        page.goto(f"{BASE}/reports", wait_until="networkidle")
        page.wait_for_timeout(1500)
        results["深色主题保持"] = page.evaluate(
            "document.documentElement.dataset.theme") == "dark"
        results["报表图表已渲染"] = page.locator(".chart-box canvas").count() > 0
        page.screenshot(path=f"{SHOTS}/theme-dark-reports.png")

        # 报表页切回浅色
        page.get_by_role("button", name="浅色").click()
        page.wait_for_timeout(1000)
        results["切回浅色"] = page.evaluate(
            "document.documentElement.dataset.theme") == "light"
        results["按钮文案随主题变化"] = (
            page.get_by_role("button", name="深色").count() == 1)
        page.screenshot(path=f"{SHOTS}/theme-light-reports.png")
        browser.close()

    print("===== 界面规格验证 =====")
    ok = True
    for k, v in results.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
        ok = ok and v
    print(f"\n结论: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
