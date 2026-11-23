"""72h 无人值守稳定性守夜测试（CPU 推理链路的水密/泄漏/接口健壮性）。

用法：
    pip install psutil
    python scripts/soak_test.py --hours 72 --coil-minutes 10          # 正式守夜
    python scripts/soak_test.py --hours 0.1 --coil-minutes 2          # 6 分钟冒烟
    python scripts/soak_test.py --no-launch                           # 附加到已启动的后端

行为：
- 自动拉起后端（或附加），admin 登录，循环"开始卷 → 采样 → 结束卷"；
- 每 sample-seconds 秒采样：后端 RSS 内存、SQLite 体积、证据帧数量、
  /api/system/status 可访问性、流水线 last_error；
- 结束后写 soak_report.json + soak_report.csv（中途 Ctrl+C 也会写出部分结果）。

判定（写入报告）：
- 内存增长（相对第 2 小时基线，测试不足 2h 时取首样本）< 15%；
- 接口错误 = 0；
- 后端进程全程存活；
- 流水线未出现 last_error。
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

try:
    import psutil
except ImportError:
    print("缺少 psutil：请先 pip install psutil")
    sys.exit(1)

PORT = 0
BASE = ""


def http_json(path: str, method: str = "GET", token: str = "",
              payload: dict | None = None, timeout: float = 15) -> dict:
    req = urllib.request.Request(BASE + path, method=method)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if method in ("POST", "PUT"):
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(payload or {}).encode("utf-8")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def wait_health(seconds: float = 120) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            http_json("/api/system/status", timeout=2)
            return True
        except Exception:
            time.sleep(1)
    return False


def main() -> int:
    global PORT, BASE
    ap = argparse.ArgumentParser(description="72h 稳定性守夜测试")
    ap.add_argument("--hours", type=float, default=72)
    ap.add_argument("--coil-minutes", type=float, default=10)
    ap.add_argument("--sample-seconds", type=float, default=60)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-launch", action="store_true", help="附加到已运行的后端")
    args = ap.parse_args()
    PORT = args.port
    BASE = f"http://127.0.0.1:{PORT}"

    backend_dir = Path(__file__).resolve().parents[1]
    db_path = backend_dir / "data" / "steel_vision.db"
    frames_dir = backend_dir / "data" / "frames"

    proc = None
    if not args.no_launch:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", str(PORT)],
            cwd=str(backend_dir))
    if not wait_health():
        print("后端未就绪，检查依赖与端口占用")
        if proc:
            proc.terminate()
        return 1

    token = ""
    try:
        login = http_json("/api/auth/login", "POST",
                          payload={"username": "admin", "password": "admin123"})
        token = login.get("token", "")
    except Exception as exc:
        print(f"登录失败（若已关闭鉴权可忽略）: {exc}")

    total = int(args.hours * 3600)
    start = time.time()
    samples: list[dict] = []
    errors = 0
    coil_i = 0

    def sample(label: str) -> None:
        nonlocal errors
        row: dict = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "t_sec": int(time.time() - start),
            "label": label,
            "rss_mb": 0.0,
            "db_mb": 0.0,
            "frames": 0,
            "running": False,
            "frame_idx": 0,
            "last_error": "",
            "api_ok": True,
        }
        try:
            if proc is not None:
                row["rss_mb"] = round(
                    psutil.Process(proc.pid).memory_info().rss / 1e6, 1)
            row["db_mb"] = round(
                db_path.stat().st_size / 1e6, 2) if db_path.exists() else 0.0
            row["frames"] = len(list(frames_dir.glob("*.jpg"))) \
                if frames_dir.exists() else 0
            st = http_json("/api/system/status", timeout=5)
            row["running"] = st["pipeline"]["running"]
            row["frame_idx"] = st["pipeline"]["frame_idx"]
            row["last_error"] = st["pipeline"].get("last_error", "")
        except Exception as exc:
            row["api_ok"] = False
            row["error"] = str(exc)
            errors += 1
        samples.append(row)

    try:
        while time.time() - start < total:
            coil_i += 1
            coil_no = f"SOAK-{time.strftime('%m%d-%H%M')}-{coil_i:03d}"
            try:
                http_json("/api/pipeline/start", "POST", token,
                          {"coil_no": coil_no})
            except Exception as exc:
                errors += 1
                print(f"start 失败: {exc}")
            coil_end = min(start + total, time.time() + args.coil_minutes * 60)
            while time.time() < coil_end:
                time.sleep(min(args.sample_seconds, max(1, coil_end - time.time())))
                sample(f"coil-{coil_i}")
            try:
                http_json("/api/pipeline/stop", "POST", token)
            except Exception as exc:
                errors += 1
                print(f"stop 失败: {exc}")
            time.sleep(3)
    except KeyboardInterrupt:
        print("\n收到中断，写出部分结果…")
    finally:
        alive = proc.poll() is None if proc is not None else True
        # 基线：第 2 小时（或首个样本）
        baseline = next((s for s in samples if s["t_sec"] >= 7200),
                        samples[0] if samples else None)
        last = samples[-1] if samples else None
        growth = 0.0
        if baseline and last and baseline["rss_mb"] > 0:
            growth = round((last["rss_mb"] - baseline["rss_mb"])
                           / baseline["rss_mb"] * 100, 2)
        report = {
            "duration_sec": int(time.time() - start),
            "coils_run": coil_i,
            "samples": len(samples),
            "api_errors": errors,
            "backend_alive": alive,
            "mem_growth_pct": growth,
            "mem_baseline_mb": baseline["rss_mb"] if baseline else 0,
            "mem_last_mb": last["rss_mb"] if last else 0,
            "db_mb_last": last["db_mb"] if last else 0,
            "frames_last": last["frames"] if last else 0,
        }
        report["verdict"] = ("PASS" if (alive and errors == 0 and growth < 15.0
                                        and (last is None or not last["last_error"]))
                             else "FAIL")
        out_json = Path(__file__).resolve().parent / "soak_report.json"
        out_json.write_text(json.dumps({"report": report, "samples": samples},
                                       ensure_ascii=False, indent=2),
                            encoding="utf-8")
        out_csv = Path(__file__).resolve().parent / "soak_report.csv"
        with out_csv.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(samples[0].keys())
                               if samples else ["ts"])
            w.writeheader()
            for s in samples:
                w.writerow(s)
        print(f"\n结论: {report['verdict']}")
        print(f"  时长 {report['duration_sec']}s · {coil_i} 卷 · 样本 {len(samples)}")
        print(f"  内存 {report['mem_baseline_mb']}→{report['mem_last_mb']}MB"
              f"（增长 {growth}%）· 接口错误 {errors} · 进程存活 {alive}")
        print(f"  报告: {out_json.name} / {out_csv.name}")
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
    return 0 if report.get("verdict") == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
