"""复核工作流演示：对一卷的待复核缺陷批量走完「确认 / 误报」流程，
并输出复核前/后的报表对比（待复核 → 已确认/误报、有效密度、判级变化）。

策略（模拟质检员的真实复核口径）：
- 高置信度（>= review_confirm_conf，默认 0.60）判为确认真实缺陷；
- 低置信度（< review_reject_conf，默认 0.30）判为误报剔除；
- 两者之间按缺陷编号确定性抽样（约 half 比例确认），保证可选、可复现。

用法：
    python scripts/review_demo.py                    # 最新一卷
    python scripts/review_demo.py --coil DEMO-1115-205444
    python scripts/review_demo.py --coil-id 12 --confirm-conf 0.6 --reject-conf 0.3
    python scripts/review_demo.py --reset            # 先把该卷复核状态清回待复核
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8000"


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


def fmt_report(rep: dict) -> str:
    return (f"  缺陷 {rep['defect_total']} | 待复核 {rep['pending']} | "
            f"已确认 {rep['confirmed']} | 误报 {rep['false_alarms']} | "
            f"有效 {rep['effective_total']}\n"
            f"  有效密度 {rep['density_per_m']} 个/米（阈值 {rep['threshold_per_m']}）"
            f" | 判级 {rep['grade']} | {rep['advice']}")


def main() -> int:
    global BASE
    ap = argparse.ArgumentParser(description="SteelVision 复核工作流演示")
    ap.add_argument("--coil", default="", help="卷号（默认最新卷）")
    ap.add_argument("--coil-id", type=int, default=0, help="卷 ID（优先于卷号）")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--confirm-conf", type=float, default=0.60)
    ap.add_argument("--reject-conf", type=float, default=0.30)
    ap.add_argument("--only", type=int, default=0, help="只处理前 N 条（0=全部）")
    ap.add_argument("--reset", action="store_true", help="先清回待复核状态")
    args = ap.parse_args()
    BASE = f"http://127.0.0.1:{args.port}"

    token = http("/api/auth/login", "POST",
                 payload={"username": "admin", "password": "admin123"})["token"]

    coil_id = args.coil_id
    if not coil_id:
        coils = http("/api/coils?limit=100")
        if not coils:
            print("无卷记录，先运行 demo_coil.py")
            return 1
        if args.coil:
            hit = [c for c in coils if c["coil_no"] == args.coil]
            if not hit:
                print(f"未找到卷 {args.coil}")
                return 1
            coil_id = hit[0]["id"]
        else:
            coil_id = coils[0]["id"]

    rep_before = http(f"/api/reports/coil/{coil_id}")
    print(f"===== 复核前 · 卷 {rep_before['coil_no']}（ID {coil_id}）=====")
    print(fmt_report(rep_before))

    defects = http(f"/api/coils/{coil_id}/defects")
    if args.reset:
        n = 0
        for d in defects:
            if d["review_status"] != "pending":
                http(f"/api/defects/{d['id']}/review", "POST", token,
                     {"status": "pending", "note": ""})
                n += 1
        print(f"\n已重置 {n} 条回待复核")
        defects = http(f"/api/coils/{coil_id}/defects")

    todo = [d for d in defects if d["review_status"] == "pending"]
    if args.only > 0:
        todo = todo[:args.only]
    if not todo:
        print("\n没有待复核缺陷")
        return 0

    confirmed = rejected = 0
    for d in todo:
        if d["conf"] >= args.confirm_conf:
            status, note = "confirmed", "复核确认"
        elif d["conf"] < args.reject_conf:
            status, note = "false_alarm", "复核剔除（低置信度误报）"
        else:
            status = "confirmed" if d["id"] % 2 == 0 else "false_alarm"
            note = "复核确认" if status == "confirmed" else "复核剔除（抽样复判）"
        http(f"/api/defects/{d['id']}/review", "POST", token,
             {"status": status, "note": note})
        if status == "confirmed":
            confirmed += 1
        else:
            rejected += 1
    print(f"\n本批复核 {len(todo)} 条：确认 {confirmed} · 误报 {rejected}")

    rep_after = http(f"/api/reports/coil/{coil_id}")
    print(f"\n===== 复核后 · 卷 {rep_after['coil_no']} =====")
    print(fmt_report(rep_after))

    d_before = rep_before["density_per_m"]
    d_after = rep_after["density_per_m"]
    print("\n===== 前后对比 =====")
    print(f"  待复核 {rep_before['pending']} → {rep_after['pending']}")
    print(f"  已确认 {rep_before['confirmed']} → {rep_after['confirmed']}")
    print(f"  误报   {rep_before['false_alarms']} → {rep_after['false_alarms']}")
    print(f"  有效密度 {d_before} → {d_after} 个/米")
    print(f"  判级 {rep_before['grade']} → {rep_after['grade']}"
          f"（{rep_before['advice']} → {rep_after['advice']}）")
    print("\n报表页/复核页数据已更新，可直接录屏演示复核闭环。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
