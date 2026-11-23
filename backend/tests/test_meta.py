"""系统元信息冒烟：版本口径（无合同号）与健康检查（完整应用含启动事件）。"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient


def test_version_and_health():
    from app.main import app as main_app

    with TestClient(main_app) as c:
        v = c.get("/version").json()
        assert v["version"] == "0.8.0"
        assert "ACHXKT" not in json.dumps(v, ensure_ascii=False)

        h = c.get("/api/health")
        assert h.status_code == 200
        assert h.json()["ok"] is True


def test_system_status_shape(client):
    resp = client.get("/api/system/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "pipeline" in body
    assert {"running", "frame_idx"} <= set(body["pipeline"].keys())
    assert isinstance(body["class_names"], list)
