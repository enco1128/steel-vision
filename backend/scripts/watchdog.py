"""看门狗：无人值守守护后端（巡检 /api/health，连续失败自动重启后端）。

与 soak_test.py 分工：
- soak_test：压测 + 指标采样 + PASS/FAIL 报告（验收用）；
- watchdog：生产陪跑（现场 72h 值守时与 uvicorn 并行运行，发现挂死/异常退出
  连发重启，保证演示与试运行期间界面始终在线）。

用法：
    python scripts/watchdog.py                 # 默认巡检 http://127.0.0.1:8000
    python scripts/watchdog.py --port 8001     # 其他端口
    python scripts/watchdog.py --no-start      # 只监控不负责拉起（外部已托管）

行为：
- 每 10s 请求 /api/health；读不到/非 200 连续 3 次 → 判定失联；
- 失联后终止旧进程（若由本脚本拉起）并重新拉起 uvicorn，指数退避（5s→60s 封顶）；
- 全部动作写 logs/watchdog.log（RotatingFileHandler），可长期无人值守。
"""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
LOG_DIR = BACKEND / "data" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            LOG_DIR / "watchdog.log", maxBytes=5 * 1024 * 1024,
            backupCount=3, encoding="utf-8"),
    ],
)
log = logging.getLogger("watchdog")


def healthy(port: int, timeout: float = 3.0) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/health", timeout=timeout) as r:
            return r.status == 200, f"HTTP {r.status}"
    except Exception as exc:
        return False, type(exc).__name__


def spawn(port: int) -> subprocess.Popen:
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(BACKEND), creationflags=flags)
    log.info("已拉起后端 pid=%s port=%s", proc.pid, port)
    return proc


def main() -> int:
    ap = argparse.ArgumentParser(description="SteelVision 看门狗")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--interval", type=float, default=10.0,
                    help="巡检间隔秒")
    ap.add_argument("--fail-threshold", type=int, default=3,
                    help="连续失败次数达到后重启")
    ap.add_argument("--no-start", action="store_true",
                    help="只监控不负责拉起后端")
    args = ap.parse_args()

    proc: subprocess.Popen | None = None
    fails = 0
    backoff = 5
    log.info("看门狗启动：port=%s interval=%ss threshold=%s manage=%s",
             args.port, args.interval, args.fail_threshold,
             not args.no_start)

    if not args.no_start:
        ok, why = healthy(args.port, timeout=1.0)
        if not ok:
            proc = spawn(args.port)

    while True:
        time.sleep(args.interval)
        try:
            ok, why = healthy(args.port)
        except Exception:
            ok, why = False, "probe-error"
        if ok:
            if fails:
                log.info("健康恢复（此前连续失败 %d 次）", fails)
            fails = 0
            backoff = 5
            continue

        fails += 1
        log.warning("健康检查失败 %d/%d（%s）", fails, args.fail_threshold, why)
        if fails < args.fail_threshold:
            continue

        log.error("判定后端失联，执行重启")
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
        if not args.no_start:
            time.sleep(backoff)
            proc = spawn(args.port)
            backoff = min(backoff * 2, 60)
        fails = 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log.info("看门狗退出")
