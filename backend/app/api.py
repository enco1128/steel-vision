"""REST API 路由：鉴权 / 卷与缺陷 / 复核 / 报警 / 报表导出 / 设置 / 流水线控制。

接口命名风格对齐 ww68y 平台与 Ultralytics 生态惯例（detect / history / report），
但底层完全自建（参考仓库仅提供设计迁移，不引入其代码）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from .core.config import settings
from .db import SessionLocal
from .models import Alarm, Coil, Defect
from .services import auth, reports
from .services.camera import adapters as camera_adapters
from .services.detector import available_providers
from .services.linkage import linkage
from .services.pipeline import pipeline

router = APIRouter()

_BEARER = "Bearer "


def current_user(request: Request) -> dict:
    if not settings.get().get("auth_enabled", True):
        return {"username": "anonymous", "role": "admin"}
    header = request.headers.get("Authorization", "")
    token = header[len(_BEARER):] if header.startswith(_BEARER) else ""
    sess = auth.verify(token)
    if not sess:
        raise HTTPException(401, "未登录或会话已过期")
    return sess


def _require_role(user: dict, roles: tuple) -> None:
    if user.get("role") not in roles:
        raise HTTPException(403, "当前角色无此操作权限")


# ------------------------------------------------------------------ 模型
class LoginBody(BaseModel):
    username: str
    password: str


class StartBody(BaseModel):
    coil_no: str = ""
    source: str = ""


class ReviewBody(BaseModel):
    status: str = "confirmed"
    note: str = ""


class SettingsBody(BaseModel):
    model_path: Optional[str] = None
    source_path: Optional[str] = None
    conf: Optional[float] = None
    iou: Optional[float] = None
    fps: Optional[float] = None
    evidence_conf: Optional[float] = None
    meters_per_frame: Optional[float] = None
    auth_enabled: Optional[bool] = None
    class_names: Optional[list[str]] = None
    alarms: Optional[dict] = None
    infer_providers: Optional[str] = None
    fp16: Optional[bool] = None
    tiling: Optional[dict] = None
    camera: Optional[dict] = None
    linkage: Optional[dict] = None
    retention: Optional[dict] = None


# ------------------------------------------------------------------ 鉴权
@router.post("/auth/login")
def login(body: LoginBody):
    with SessionLocal() as db:
        token, user = auth.login(db, body.username, body.password)
    if not token:
        raise HTTPException(401, "用户名或密码错误")
    return {"token": token, "user": user}


@router.post("/auth/logout")
def logout(request: Request):
    header = request.headers.get("Authorization", "")
    auth.logout(header[len(_BEARER):] if header.startswith(_BEARER) else "")
    return {"ok": True}


# ------------------------------------------------------------------ 系统状态
@router.get("/system/status")
def system_status():
    cfg = settings.get()
    workspace = Path(__file__).resolve().parents[2].parent  # 上层工作区
    candidates = [
        workspace / "steel-surface-defect" / "datasets" / "processed" / "neu_det" / "images" / "test",
        workspace / "steel-surface-defect" / "datasets" / "processed" / "gc10det" / "images" / "test",
        workspace / "steel-surface-defect" / "datasets" / "raw",
        workspace / "steel-surface-defect" / "datasets" / "raw" / "customer",
        workspace / "steel-surface-defect" / "datasets" / "processed" / "customer" / "images" / "test",
    ]
    return {
        "pipeline": pipeline.status(),
        "model_exists": Path(cfg.get("model_path", "")).exists(),
        "model_path": cfg.get("model_path", ""),
        "source_presets": [str(p) for p in candidates if p.exists()],
        "class_names": cfg.get("class_names", []),
    }


# ------------------------------------------------------------------ 流水线
@router.post("/pipeline/start")
def pipeline_start(body: StartBody, user: dict = Depends(current_user)):
    _require_role(user, ("admin", "operator"))
    try:
        return pipeline.start(source=body.source, coil_no=body.coil_no)
    except FileNotFoundError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


@router.post("/pipeline/stop")
def pipeline_stop(user: dict = Depends(current_user)):
    _require_role(user, ("admin", "operator"))
    return pipeline.stop()


# ------------------------------------------------------------------ 卷与缺陷
def _coil_dict(c: Coil) -> dict:
    return {"id": c.id, "coil_no": c.coil_no, "start_ts": c.start_ts,
            "end_ts": c.end_ts, "status": c.status, "source": c.source,
            "defect_count": c.defect_count, "length_m": c.length_m,
            "frames_total": c.frames_total, "quality_grade": c.quality_grade}


def _defect_dict(d: Defect) -> dict:
    return {"id": d.id, "coil_id": d.coil_id, "ts": d.ts,
            "frame_idx": d.frame_idx, "class_id": d.class_id,
            "cls_name": d.cls_name, "conf": d.conf,
            "x1": d.x1, "y1": d.y1, "x2": d.x2, "y2": d.y2,
            "evidence_path": d.evidence_path,
            "review_status": d.review_status, "review_note": d.review_note}


@router.get("/coils")
def list_coils(limit: int = 100):
    with SessionLocal() as db:
        rows = (db.query(Coil).order_by(Coil.id.desc()).limit(limit).all())
        return [_coil_dict(c) for c in rows]


@router.get("/coils/{coil_id}/defects")
def coil_defects(coil_id: int):
    with SessionLocal() as db:
        rows = (db.query(Defect).filter(Defect.coil_id == coil_id)
                .order_by(Defect.id.desc()).all())
        return [_defect_dict(d) for d in rows]


@router.get("/evidence/{defect_id}")
def evidence(defect_id: int):
    with SessionLocal() as db:
        d = db.get(Defect, defect_id)
    if not d or not d.evidence_path or not Path(d.evidence_path).exists():
        raise HTTPException(404, "该缺陷无证据帧")
    return FileResponse(d.evidence_path, media_type="image/jpeg")


@router.post("/defects/{defect_id}/review")
def review(defect_id: int, body: ReviewBody, user: dict = Depends(current_user)):
    _require_role(user, ("admin", "operator"))
    if body.status not in ("pending", "confirmed", "false_alarm"):
        raise HTTPException(400, "非法复核状态")
    with SessionLocal() as db:
        d = db.get(Defect, defect_id)
        if d is None:
            raise HTTPException(404, "缺陷不存在")
        d.review_status = body.status
        d.review_note = body.note
        db.commit()
        return _defect_dict(d)


# ------------------------------------------------------------------ 报警
@router.get("/alarms")
def list_alarms(limit: int = 200, only_unacked: bool = False):
    with SessionLocal() as db:
        q = db.query(Alarm).order_by(Alarm.id.desc())
        if only_unacked:
            q = q.filter(Alarm.acked == 0)
        rows = q.limit(limit).all()
        return [{"id": a.id, "coil_id": a.coil_id, "rule": a.rule,
                 "level": a.level, "message": a.message, "ts": a.ts,
                 "acked": a.acked, "acked_by": a.acked_by} for a in rows]


@router.post("/alarms/{alarm_id}/ack")
def ack_alarm(alarm_id: int, user: dict = Depends(current_user)):
    _require_role(user, ("admin", "operator"))
    with SessionLocal() as db:
        a = db.get(Alarm, alarm_id)
        if a is None:
            raise HTTPException(404, "报警不存在")
        a.acked = 1
        a.acked_by = user.get("username", "")
        db.commit()
        return {"ok": True}


# ------------------------------------------------------------------ 报表与导出
@router.get("/reports/coil/{coil_id}")
def coil_report(coil_id: int):
    with SessionLocal() as db:
        rep = reports.coil_report(db, coil_id, settings.get())
    if rep is None:
        raise HTTPException(404, "卷不存在")
    return rep


@router.get("/reports/coil/{coil_id}/export.csv")
def export_csv(coil_id: int):
    with SessionLocal() as db:
        text = reports.export_csv(db, coil_id)
    return PlainTextResponse(
        text, media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="coil_{coil_id}_defects.csv"'})


@router.get("/reports/coil/{coil_id}/export.html", response_class=HTMLResponse)
def export_html(coil_id: int):
    with SessionLocal() as db:
        return reports.export_html(db, coil_id, settings.get())


# ------------------------------------------------------------------ 模型热切换
class ModelBody(BaseModel):
    model_path: str
    class_names: Optional[list[str]] = None


@router.get("/model/info")
def model_info():
    cfg = settings.get()
    st = pipeline.status()
    return {
        "model_path": cfg.get("model_path", ""),
        "class_names": cfg.get("class_names", []),
        "infer_providers": cfg.get("infer_providers", "auto"),
        "fp16": cfg.get("fp16", False),
        "tiling": cfg.get("tiling", {}),
        "backend": st.get("backend", ""),
        "provider": st.get("provider", ""),
        "available_providers": available_providers(),
        "camera_adapters": camera_adapters(),
    }


@router.post("/model/reload")
def model_reload(body: ModelBody, user: dict = Depends(current_user)):
    _require_role(user, ("admin",))
    if pipeline.status().get("running"):
        raise HTTPException(409, "检测运行中不可热切换模型，请先结束本卷")
    patch: dict = {"model_path": body.model_path}
    if body.class_names is not None:
        patch["class_names"] = body.class_names
    cfg = settings.update(patch)
    return {"ok": True, "model_path": cfg["model_path"],
            "class_names": cfg["class_names"],
            "note": "下次『开始检测』生效",
            "available_providers": available_providers()}


# ------------------------------------------------------------------ 外联动
@router.post("/linkage/test")
def linkage_test(user: dict = Depends(current_user)):
    _require_role(user, ("admin", "operator"))
    return linkage.test(settings.get())


# ------------------------------------------------------------------ 设置
@router.get("/settings")
def get_settings():
    return settings.get()


@router.put("/settings")
def put_settings(body: SettingsBody, user: dict = Depends(current_user)):
    _require_role(user, ("admin",))
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    return settings.update(patch)
