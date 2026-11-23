"""报警引擎：规则判定 + 去重上报。

规则模型迁移自 ThingsBoard（Apache-2.0）的"规则 + 事件 + 确认(ack)"工作流，
报警分级（info/warn/critical）参照 SCADA-LTS 的做法。
同一卷同一规则只上报一次，避免逐帧刷屏。
"""
from __future__ import annotations


def _exists(db, coil_id: int, rule: str) -> bool:
    from ..models import Alarm

    return db.query(Alarm).filter(Alarm.coil_id == coil_id,
                                  Alarm.rule == rule).first() is not None


def raise_alarm(db, coil_id: int, rule: str, level: str, message: str):
    from ..models import Alarm

    if _exists(db, coil_id, rule):
        return None
    alarm = Alarm(coil_id=coil_id, rule=rule, level=level, message=message)
    db.add(alarm)
    db.commit()
    db.refresh(alarm)
    return {"id": alarm.id, "coil_id": alarm.coil_id, "rule": alarm.rule,
            "level": alarm.level, "message": alarm.message, "ts": alarm.ts,
            "acked": 0}


def eval_defect_alarm(db, coil, defect, cfg: dict) -> list[dict]:
    """逐缺陷规则：高优先级类别命中 + 单卷缺陷数阈值跨越。"""
    from ..models import Defect

    created: list[dict] = []
    acfg = cfg.get("alarms", {})
    priority = set(acfg.get("priority_classes", []))
    ev_conf = float(cfg.get("evidence_conf", 0.5))

    if defect.cls_name in priority and defect.conf >= min(ev_conf, 0.5):
        a = raise_alarm(
            db, coil.id, f"priority:{defect.cls_name}", "critical",
            f"卷 {coil.coil_no} 检出高优先级缺陷【{defect.cls_name}】conf={defect.conf:.3f}")
        if a:
            created.append(a)

    total = db.query(Defect).filter(Defect.coil_id == coil.id).count()
    threshold = int(acfg.get("min_defects_per_coil", 8))
    if total == threshold:
        a = raise_alarm(
            db, coil.id, "count", "warn",
            f"卷 {coil.coil_no} 缺陷数达到阈值 {threshold}")
        if a:
            created.append(a)
    return created
