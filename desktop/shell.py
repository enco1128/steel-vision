"""PyQt5 桌面壳：内嵌与 Web 完全相同的工业 HMI。

融合策略（轨道 A + 轨道 B 合一）：
- 一套后端（FastAPI + SQLite + CPU 推理流水线）+ 一套前端（Vue3 HMI）；
- PyQt5 桌面壳只是本机 kiosk 容器（QWebEngineView + 自动拉起后端），
  与浏览器访问是同一系统、同一数据库、同一 API —— 不存在两套 UI 维护成本；
- 对应交付形态：软件原型（桌面可执行形态）与 Web 形态自由切换。

运行：
    pip install -r requirements-desktop.txt
    python shell.py
快捷键：F11 全屏切换；Esc 退出全屏；关闭窗口自动结束后端进程。
"""
from __future__ import annotations

import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtWidgets import QApplication, QMainWindow, QMessageBox
from PyQt5.QtWebEngineWidgets import QWebEngineView

PORT = 8000
BASE = f"http://127.0.0.1:{PORT}"


def _healthy() -> bool:
    try:
        urllib.request.urlopen(f"{BASE}/api/system/status", timeout=1)
        return True
    except Exception:
        return False


def ensure_backend() -> "subprocess.Popen | None":
    """后端未运行时自动拉起（uvicorn 子进程，与训练进程互不影响）。"""
    if _healthy():
        return None
    backend_dir = Path(__file__).resolve().parents[1] / "backend"
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=str(backend_dir),
        creationflags=creationflags,
    )
    for _ in range(120):          # 最长等待 60s（首次启动初始化数据库）
        time.sleep(0.5)
        if _healthy():
            break
    return proc


class MainWindow(QMainWindow):
    def __init__(self, proc) -> None:
        super().__init__()
        self._proc = proc
        self.setWindowTitle("SteelVision · 带钢表面缺陷检测系统 v0.8")
        self.resize(1680, 960)
        self.view = QWebEngineView(self)
        self.view.setUrl(QUrl(BASE))
        self.setCentralWidget(self.view)
        self.statusBar().showMessage(
            "F11 全屏 / Esc 退出全屏｜CPU 推理，与训练进程隔离｜左侧导航五页：监控·复核·报表·报警·设置")

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_F11:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()
        elif event.key() == Qt.Key_Escape and self.isFullScreen():
            self.showNormal()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        if self._proc is not None:
            self._proc.terminate()
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    proc = ensure_backend()
    if not _healthy():
        QMessageBox.critical(
            None, "启动失败",
            "后端服务未能启动。\n请先在 backend 目录安装依赖：\n"
            "  pip install -r requirements.txt")
        if proc is not None:
            proc.terminate()
        return 1
    win = MainWindow(proc)
    win.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
