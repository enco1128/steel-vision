"""报警规则单测：优先级类命中 / 计数阈值 / 去重。"""
from __future__ import annotations

import copy
import uuid

from app.core.config import DEFAULTS
from app.models import Coil, Defect
from app.services.alarms import eval_defect_alarm


def _cfg():
    return copy.deepcopy(DEFAULTS)


def _coil(db):
    coil = Coil(coil_no=f"A-{uuid.uuid4().hex[:8]}", status="running")
    db.add(coil)
    db.commit()
    db.refresh(coil)
    return coil


def _defect(db, coil, cls_name="patches", conf=0.9):
    d = Defect(coil_id=coil.id, cls_name=cls_name, conf=conf)
    db.add(d)
    db.commit()
    db.refresh(d)
    return d


def test_priority_alarm_and_dedupe(db):
    cfg = _cfg()
    coil = _coil(db)
    d = _defect(db, coil, cls_name="inclusion", conf=0.9)
    created = eval_defect_alarm(db, coil, d, cfg)
    assert [a["rule"] for a in created] == ["priority:inclusion"]
    assert created[0]["level"] == "critical"
    # 同卷同规则只报一次
    assert eval_defect_alarm(db, coil, d, cfg) == []


def test_priority_gate_low_confidence(db):
    cfg = _cfg()  # evidence_conf=0.5 → 优先级门限 0.5
    coil = _coil(db)
    d = _defect(db, coil, cls_name="rolled-in scale", conf=0.3)
    assert eval_defect_alarm(db, coil, d, cfg) == []


def test_count_threshold_fires_exactly_once(db):
    cfg = _cfg()  # min_defects_per_coil=8
    coil = _coil(db)
    fired: list[str] = []
    for _ in range(10):
        d = _defect(db, coil, cls_name="patches", conf=0.8)
        fired += [a["rule"] for a in eval_defect_alarm(db, coil, d, cfg)]
    assert fired.count("count") == 1  # 第 8 条缺陷（总数恰为阈值）时触发一次


def test_custom_count_threshold(db):
    cfg = _cfg()
    cfg["alarms"]["min_defects_per_coil"] = 3
    coil = _coil(db)
    fired: list[str] = []
    for _ in range(4):
        d = _defect(db, coil, cls_name="patches", conf=0.8)
        fired += [a["rule"] for a in eval_defect_alarm(db, coil, d, cfg)]
    assert fired.count("count") == 1
