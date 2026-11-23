"""鉴权与权限矩阵：登录/登出/匿名拒绝/角色隔离。"""
from __future__ import annotations


def test_login_success(client):
    resp = client.post("/api/auth/login",
                       json={"username": "admin", "password": "admin123"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["token"]) == 32
    assert body["user"] == {"username": "admin", "role": "admin"}


def test_login_bad_password(client):
    resp = client.post("/api/auth/login",
                       json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401


def test_anonymous_rejected(client):
    assert client.post("/api/pipeline/stop").status_code == 401
    assert client.post("/api/pipeline/start",
                       json={"coil_no": "", "source": ""}).status_code == 401
    resp = client.get("/api/settings")  # 只读接口不鉴权（原型口径）
    assert resp.status_code == 200


def test_logout_invalidates_token(client):
    token = client.post("/api/auth/login",
                        json={"username": "operator",
                              "password": "operator123"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    # 登录态可过鉴权（走到 404：报警不存在，说明已进入业务层）
    assert client.post("/api/alarms/999999/ack",
                       headers=headers).status_code == 404
    client.post("/api/auth/logout", headers=headers)
    assert client.post("/api/alarms/999999/ack",
                       headers=headers).status_code == 401


def test_role_matrix_ack(client, operator_h, viewer_h):
    # 仅读角色禁止写操作；admin/operator 放行（此处报 404 说明已过权限关）
    assert client.post("/api/alarms/999999/ack",
                       headers=viewer_h).status_code == 403
    assert client.post("/api/alarms/999999/ack",
                       headers=operator_h).status_code == 404


def test_role_matrix_settings(client, admin_h, operator_h, viewer_h):
    # 设置写权限仅 admin
    assert client.put("/api/settings", json={"conf": 0.4},
                      headers=viewer_h).status_code == 403
    assert client.put("/api/settings", json={"conf": 0.4},
                      headers=operator_h).status_code == 403
    resp = client.put("/api/settings", json={"conf": 0.42},
                      headers=admin_h)
    assert resp.status_code == 200
    assert resp.json()["conf"] == 0.42


def test_model_reload_admin_only(client, operator_h):
    assert client.post("/api/model/reload",
                       json={"model_path": "x.pt"},
                       headers=operator_h).status_code == 403
