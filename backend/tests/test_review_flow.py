"""复核 API：状态流转 / 权限 / 报表联动（误报剔除影响判级）。"""
from __future__ import annotations

import uuid

from app.models import Coil, Defect


def _coil_and_defect(db):
    coil = Coil(coil_no=f"RV-{uuid.uuid4().hex[:8]}", status="closed",
                length_m=10.0, start_ts="2026-11-15 10:00:00",
                end_ts="2026-11-15 10:10:00")
    db.add(coil)
    db.commit()
    db.refresh(coil)
    d = Defect(coil_id=coil.id, cls_name="patches", conf=0.8)
    db.add(d)
    db.commit()
    db.refresh(d)
    return coil, d


def test_review_requires_login(client, db):
    _, d = _coil_and_defect(db)
    resp = client.post(f"/api/defects/{d.id}/review",
                       json={"status": "confirmed"})
    assert resp.status_code == 401


def test_viewer_cannot_review(client, db, viewer_h):
    _, d = _coil_and_defect(db)
    resp = client.post(f"/api/defects/{d.id}/review",
                       json={"status": "confirmed"}, headers=viewer_h)
    assert resp.status_code == 403


def test_review_transitions_and_report_linkage(client, db, operator_h):
    coil, d = _coil_and_defect(db)

    resp = client.post(f"/api/defects/{d.id}/review",
                       json={"status": "confirmed", "note": "复核确认"},
                       headers=operator_h)
    assert resp.status_code == 200
    assert resp.json()["review_status"] == "confirmed"
    rep = client.get(f"/api/reports/coil/{coil.id}").json()
    assert rep["confirmed"] == 1 and rep["pending"] == 0
    assert rep["effective_total"] == 1 and rep["grade"] == "B"

    # confirmed → false_alarm：允许推翻判定，报表联动剔除、判级回 A
    resp = client.post(f"/api/defects/{d.id}/review",
                       json={"status": "false_alarm", "note": "抽样复判误报"},
                       headers=operator_h)
    assert resp.status_code == 200
    assert resp.json()["review_status"] == "false_alarm"
    rep = client.get(f"/api/reports/coil/{coil.id}").json()
    assert rep["false_alarms"] == 1
    assert rep["effective_total"] == 0
    assert rep["grade"] == "A"


def test_review_invalid_status(client, db, operator_h):
    _, d = _coil_and_defect(db)
    resp = client.post(f"/api/defects/{d.id}/review",
                       json={"status": "bogus"}, headers=operator_h)
    assert resp.status_code == 400


def test_review_unknown_defect(client, operator_h):
    resp = client.post("/api/defects/999999/review",
                       json={"status": "confirmed"}, headers=operator_h)
    assert resp.status_code == 404


def test_alarm_ack_flow(client, db, operator_h):
    from app.models import Alarm

    coil, _ = _coil_and_defect(db)
    alarm = Alarm(coil_id=coil.id, rule="count", level="warn",
                  message="测试报警")
    db.add(alarm)
    db.commit()
    db.refresh(alarm)

    resp = client.post(f"/api/alarms/{alarm.id}/ack", headers=operator_h)
    assert resp.status_code == 200
    rows = client.get("/api/alarms?only_unacked=true&limit=500").json()
    assert all(a["id"] != alarm.id for a in rows)
