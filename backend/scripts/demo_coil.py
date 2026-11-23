"""演示数据取样：用真实缺陷样本跑一卷，把复核/报表/报警页面的数据填起来。

用途：录屏/评审前跑一次，让各页面有真实数据可展示（不是假数据）。
重复执行会生成新的演示卷（卷号带时间戳），旧卷保留可查。

用法：
    python scripts/demo_coil.py                     # 默认 NEU 测试集 30 秒
    python scripts/demo_coil.py <数据源> <秒数>     # 自定义目录/视频与时长
    python scripts/demo_coil.py --port 8000
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
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
    global BASE
    ap = argparse.ArgumentParser(description="SteelVision 演示卷取样")
    ap.add_argument("source", nargs="?", default=DEFAULT_SOURCE)
    ap.add_argument("seconds", nargs="?", type=float, default=30.0)
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    BASE = f"http://127.0.0.1:{args.port}"

    token = http("/api/auth/login", "POST",
                 payload={"username": "admin", "password": "admin123"})["token"]

    coil_no = time.strftime("DEMO-%m%d-%H%M%S")
    started = http("/api/pipeline/start", "POST", token,
                   {"coil_no": coil_no, "source": args.source})
    print(f"演示卷已启动: {coil_no} | 模型 {started['model']} | "
          f"{started['backend']}/{started['provider']}")
    print(f"数据源: {args.source}")

    deadline = time.time() + args.seconds
    last_idx = 0
    while time.time() < deadline:
        time.sleep(5)
        st = http("/api/system/status")["pipeline"]
        if st.get("last_error"):
            print(f"流水线异常: {st['last_error']}")
            break
        if st["frame_idx"] == last_idx and st["frame_idx"] > 0:
            print("数据源已读完，提前结束")
            break
        last_idx = st["frame_idx"]
        print(f"  已处理 {last_idx} 帧…")

    http("/api/pipeline/stop", "POST", token)
    for _ in range(30):
        time.sleep(2)
        if not http("/api/system/status")["pipeline"]["running"]:
            break

    coils = http("/api/coils?limit=1")
    coil = coils[0]
    rep = http(f"/api/reports/coil/{coil['id']}")
    alarms = http("/api/alarms?limit=500")
    coil_alarms = [a for a in alarms if a["coil_id"] == coil["id"]]
    pending = sum(1 for d in http(f"/api/coils/{coil['id']}/defects")
                  if d["review_status"] == "pending")

    print("\n===== 演示卷结果 =====")
    print(f"卷号 {coil['coil_no']} | 状态 {coil['status']} | 判级 {coil['quality_grade']}")
    print(f"缺陷 {rep['defect_total']} 个（待复核 {pending}）| 有效密度 "
          f"{rep['density_per_m']} 个/米 | 长度 {rep['length_m']} 米")
    print(f"报警 {len(coil_alarms)} 条: " +
          ("、".join(f"[{a['level']}]{a['rule']}" for a in coil_alarms) or "无"))
    print(f"类别分布: {rep['counts']}")
    print("报表/复核/报警页面数据已就绪，可直接录屏。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
