"""pytest 基座：临时数据目录 + 轻量 API 实例 + 角色令牌 + 配置隔离。

隔离要点：
- SV_DATA 必须在导入 app.db 之前指向临时目录（数据库与证据帧不落真数据）；
- settings 单例加载自真 config.json，测试前强制确定性参数，结束后整体还原；
- Settings.update 写盘路径 monkeypatch 到 tmp_path，避免污染 backend/config.json。
"""
from __future__ import annotations

import os
import tempfile

os.environ["SV_DATA"] = tempfile.mkdtemp(prefix="sv_test_")

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api import router  # noqa: E402
from app.core import config as config_module  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _bootstrap():
    init_db()
    # 测试所需的确定性参数（结束后由函数级 fixture 还原）
    settings._data["auth_enabled"] = True
    settings._data["evidence_conf"] = 0.5
    settings._data["alarms"] = {
        "min_defects_per_coil": 8,
        "density_per_m": 2.0,
        "priority_classes": ["inclusion", "rolled-in scale"],
    }
    yield


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="session")
def client(_bootstrap):
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return TestClient(app)


def _login(client: TestClient, username: str, password: str) -> dict:
    resp = client.post("/api/auth/login",
                       json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


@pytest.fixture(scope="session")
def admin_h(client):
    return _login(client, "admin", "admin123")


@pytest.fixture(scope="session")
def operator_h(client):
    return _login(client, "operator", "operator123")


@pytest.fixture(scope="session")
def viewer_h(client):
    return _login(client, "viewer", "viewer123")


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch, tmp_path):
    snapshot = {k: (dict(v) if isinstance(v, dict) else v)
                for k, v in settings._data.items()}
    monkeypatch.setattr(config_module, "CONFIG_PATH", tmp_path / "config.json")
    yield
    settings._data = snapshot
