"""桌面壳 F11 验证：找到 SteelVision Qt 窗口 → 归位为常规窗口 → 发 F11
→ 比对窗口矩形与屏幕尺寸 → 再发 F11 恢复。仅依赖 ctypes，无需 pywin32。

注意：浏览器页面 <title> 同样含 SteelVision，枚举时必须排除浏览器窗口，
并按带版本号的 Qt 标题精确匹配，否则会拿到最大化状态的 Chrome 误判。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
import time

user32 = ctypes.windll.user32
VK_F11 = 0x7A
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSCOMMAND = 0x0112
SC_RESTORE = 0xF120
_BROWSER = ("Chrome", "Edge", "Firefox", "Brave", "Opera", "Vivaldi")


def _title(hwnd: int) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    if n == 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def find_window(needle: str) -> int:
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        t = _title(hwnd)
        if needle in t and not any(b in t for b in _BROWSER):
            found.append(hwnd)
            return False
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else 0


def rect(hwnd: int) -> tuple[int, int, int, int]:
    r = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def size(hwnd: int) -> tuple[int, int]:
    r = rect(hwnd)
    return r[2] - r[0], r[3] - r[1]


def send_f11(hwnd: int) -> None:
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.4)
    user32.PostMessageW(hwnd, WM_KEYDOWN, VK_F11, 0)
    user32.PostMessageW(hwnd, WM_KEYUP, VK_F11, 0)
    time.sleep(1.6)


def is_fullscreen(hwnd: int, sw: int, sh: int) -> bool:
    l, t, r, b = rect(hwnd)
    return l <= 0 and t <= 0 and (r - l) >= sw and (b - t) >= sh


def main() -> int:
    hwnd = find_window("带钢表面缺陷检测系统 v0.8")
    if not hwnd:
        hwnd = find_window("SteelVision")
    if not hwnd:
        print("FAIL: 未找到 SteelVision 桌面壳窗口（已排除浏览器）")
        return 1
    sw = user32.GetSystemMetrics(0)
    sh = user32.GetSystemMetrics(1)
    print(f"窗口 hwnd={hwnd} 标题=[{_title(hwnd)}]")
    print(f"屏幕 {sw}x{sh}")

    # 归位：最小化 → 还原；全屏/最大化 → SC_RESTORE，保证起点可判
    if user32.IsIconic(hwnd) or is_fullscreen(hwnd, sw, sh):
        user32.SetForegroundWindow(hwnd)
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.PostMessageW(hwnd, WM_SYSCOMMAND, SC_RESTORE, 0)
        time.sleep(1.2)
    w0, h0 = size(hwnd)
    print(f"起点窗口尺寸: {w0}x{h0}（应小于屏幕）")
    if w0 >= sw and h0 >= sh:
        print("FAIL: 无法归位为常规窗口")
        return 2

    send_f11(hwnd)
    full = is_fullscreen(hwnd, sw, sh)
    w1, h1 = size(hwnd)
    print(f"F11 后尺寸: {w1}x{h1} | 全屏={'YES' if full else 'NO'}")

    send_f11(hwnd)
    back = not is_fullscreen(hwnd, sw, sh)
    w2, h2 = size(hwnd)
    print(f"再按 F11 尺寸: {w2}x{h2} | 已还原={'YES' if back else 'NO'}")

    ok = full and back
    print(f"\n桌面壳 F11 结论: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
