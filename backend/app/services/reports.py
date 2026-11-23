"""按卷统计报表：汇总、质量判级、CSV / HTML 导出。

报表组织范式对齐 SCADA-LTS 的"批次历史报表"，业务化输出
（等级 + 处置建议）参考布料检测类工业实践：把缺陷统计翻译成放行决策。
"""
from __future__ import annotations

import html
import time
from collections import Counter


def _duration(coil) -> float:
    try:
        t1 = time.mktime(time.strptime(coil.start_ts, "%Y-%m-%d %H:%M:%S"))
        t2 = time.mktime(time.strptime(coil.end_ts, "%Y-%m-%d %H:%M:%S"))
        return max(0.0, t2 - t1)
    except Exception:
        return 0.0


def coil_report(db, coil_id: int, cfg: dict):
    from ..models import Coil, Defect

    coil = db.get(Coil, coil_id)
    if coil is None:
        return None
    defects = db.query(Defect).filter(Defect.coil_id == coil_id).all()
    counts = Counter(d.cls_name for d in defects)
    confirmed = sum(1 for d in defects if d.review_status == "confirmed")
    false_alarms = sum(1 for d in defects if d.review_status == "false_alarm")
    pending = len(defects) - confirmed - false_alarms
    effective = len(defects) - false_alarms          # 复核剔除误报后的有效缺陷数
    length = float(coil.length_m or 0.0)
    density = round(effective / length, 2) if length > 0 else 0.0
    th = float(cfg.get("alarms", {}).get("density_per_m", 2.0))

    if effective == 0:
        grade, advice = "A", "放行（未检出有效缺陷）"
    elif density <= th:
        grade, advice = "B", "放行 / 常规抽检"
    else:
        grade, advice = "C", "复检或降级处理"
    return {
        "coil_id": coil.id, "coil_no": coil.coil_no,
        "start_ts": coil.start_ts, "end_ts": coil.end_ts,
        "status": coil.status, "source": coil.source,
        "frames_total": coil.frames_total, "length_m": length,
        "defect_total": len(defects), "effective_total": effective,
        "confirmed": confirmed, "false_alarms": false_alarms,
        "pending": pending, "counts": dict(counts),
        "density_per_m": density, "threshold_per_m": th,
        "duration_sec": round(_duration(coil), 1),
        "grade": grade, "advice": advice,
    }


def export_csv(db, coil_id: int) -> str:
    from ..models import Defect

    defects = (db.query(Defect).filter(Defect.coil_id == coil_id)
               .order_by(Defect.id.asc()).all())
    lines = ["\ufeff缺陷ID,时间,帧号,类别,置信度,X1,Y1,X2,Y2,复核状态,复核备注,证据帧"]
    for d in defects:
        lines.append(",".join([
            str(d.id), d.ts, str(d.frame_idx), d.cls_name, f"{d.conf:.4f}",
            f"{d.x1:.1f}", f"{d.y1:.1f}", f"{d.x2:.1f}", f"{d.y2:.1f}",
            d.review_status, (d.review_note or "").replace(",", "；"),
            d.evidence_path or "-",
        ]))
    return "\r\n".join(lines)


def export_html(db, coil_id: int, cfg: dict) -> str:
    from ..models import Defect

    rep = coil_report(db, coil_id, cfg)
    if rep is None:
        return "<h3>卷不存在</h3>"
    defects = (db.query(Defect).filter(Defect.coil_id == coil_id)
               .order_by(Defect.id.asc()).all())
    rows = "\n".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{:.3f}</td>"
        "<td>{}</td><td>{}</td></tr>".format(
            d.id, d.ts, html.escape(d.cls_name), d.conf,
            d.review_status, html.escape((d.review_note or "")[:60]))
        for d in defects)
    counts = "，".join(f"{html.escape(k)}：{v} 处"
                       for k, v in rep["counts"].items()) or "无"
    return f"""<!doctype html><html lang="zh"><meta charset="utf-8">
<title>卷 {html.escape(rep['coil_no'])} 检测报告</title>
<style>
 body{{font-family:"Microsoft YaHei",sans-serif;margin:32px auto;max-width:960px;color:#1c2433}}
 h2{{border-bottom:3px solid #2563eb;padding-bottom:8px}}
 .kpis{{display:flex;gap:16px;flex-wrap:wrap;margin:18px 0}}
 .kpi{{flex:1;min-width:140px;border:1px solid #d7dee8;border-radius:8px;padding:12px 16px}}
 .kpi b{{display:block;font-size:26px;margin-top:6px}}
 table{{border-collapse:collapse;width:100%;margin-top:12px}}
 th,td{{border:1px solid #d7dee8;padding:6px 10px;font-size:13px;text-align:left}}
 th{{background:#f1f5f9}}
 .grade{{font-size:34px;color:#b91c1c}}
</style>
<h2>带钢表面缺陷检测报告 · 卷 {html.escape(rep['coil_no'])}</h2>
<p>检测时间：{rep['start_ts']} — {rep['end_ts'] or '进行中'}｜数据源：{html.escape(rep['source'] or '（合成帧）')}｜
帧数：{rep['frames_total']}｜带钢长度：{rep['length_m']} m</p>
<div class="kpis">
 <div class="kpi">检出缺陷<b>{rep['defect_total']}</b></div>
 <div class="kpi">复核确认<b>{rep['confirmed']}</b></div>
 <div class="kpi">误报剔除<b>{rep['false_alarms']}</b></div>
 <div class="kpi">缺陷密度<b>{rep['density_per_m']} 个/米</b></div>
 <div class="kpi">质量等级<b class="grade">{rep['grade']}</b></div>
</div>
<p>类别分布：{counts}｜处置建议：<b>{rep['advice']}</b>（阈值 {rep['threshold_per_m']} 个/米）</p>
<h3>缺陷明细</h3>
<table><tr><th>ID</th><th>时间</th><th>类别</th><th>置信度</th><th>复核</th><th>备注</th></tr>
{rows}
</table>
<p style="color:#64748b;font-size:12px;margin-top:24px">由 SteelVision v0.6 自动生成（检测协议与实验工程
steel-surface-defect 一致：YOLO11s 基线/改进权重，统一评测口径）</p>
</html>"""
