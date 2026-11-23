"""报表判级：A/B/C 边界、误报剔除、待复核口径、导出内容。"""
from __future__ import annotations

import copy
import uuid

from app.core.config import DEFAULTS
from app.models import Coil, Defect
from app.services import reports


def _cfg():
    cfg = copy.deepcopy(DEFAULTS)
    cfg["alarms"]["density_per_m"] = 2.0
    return cfg


def _coil(db, length_m=10.0):
    coil = Coil(coil_no=f"R-{uuid.uuid4().hex[:8]}", status="closed",
                length_m=length_m, start_ts="2026-11-15 10:00:00",
                end_ts="2026-11-15 10:10:00")
    db.add(coil)
    db.commit()
    db.refresh(coil)
    return coil


def _defects(db, coil, n, status="pending", cls_name="patches"):
    for _ in range(n):
        db.add(Defect(coil_id=coil.id, cls_name=cls_name, conf=0.8,
                      review_status=status))
    db.commit()


def test_grade_a_when_no_effective(db):
    coil = _coil(db)
    _defects(db, coil, 5, status="false_alarm")
    rep = reports.coil_report(db, coil.id, _cfg())
    assert rep["effective_total"] == 0
    assert rep["grade"] == "A"
    assert rep["density_per_m"] == 0.0


def test_grade_b_at_threshold_inclusive(db):
    coil = _coil(db, length_m=10.0)
    _defects(db, coil, 20, status="confirmed")  # 20/10 = 2.0 == 阈值 → B
    rep = reports.coil_report(db, coil.id, _cfg())
    assert rep["density_per_m"] == 2.0
    assert rep["grade"] == "B"


def test_grade_c_above_threshold(db):
    coil = _coil(db, length_m=10.0)
    _defects(db, coil, 21, status="confirmed")  # 2.1 > 2.0 → C
    rep = reports.coil_report(db, coil.id, _cfg())
    assert rep["density_per_m"] == 2.1
    assert rep["grade"] == "C"


def test_pending_counts_false_alarm_excluded(db):
    coil = _coil(db, length_m=10.0)
    _defects(db, coil, 10, status="pending")
    _defects(db, coil, 10, status="false_alarm")
    rep = reports.coil_report(db, coil.id, _cfg())
    assert rep["effective_total"] == 10  # 待复核计入、误报剔除
    assert rep["density_per_m"] == 1.0
    assert rep["pending"] == 10
    assert rep["false_alarms"] == 10
    assert rep["grade"] == "B"


def test_exports_content(db):
    coil = _coil(db)
    _defects(db, coil, 2, status="confirmed", cls_name="inclusion")
    csv_text = reports.export_csv(db, coil.id)
    assert csv_text.splitlines()[0].strip("\ufeff").startswith("缺陷ID")
    assert "inclusion" in csv_text
    html_text = reports.export_html(db, coil.id, _cfg())
    assert coil.coil_no in html_text
    assert "检测报告" in html_text
