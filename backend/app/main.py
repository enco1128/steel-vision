"""FastAPI 入口：REST + WebSocket 实时帧推流 + 前端静态托管 + 运维能力。

稳定性设计（对标 Frigate/ThingsBoard 的生产部署习惯）：
- RotatingFileHandler 日志落盘（10MB×5），uvicorn 日志一并收集；
- /api/health 健康检查（进程/数据库/流水线/磁盘），供值守脚本与外部探针使用；
- 全局异常兜底：任何未捕获异常返回结构化 500 并落日志，不拖垮进程；
- WebSocket 逐客户端背压：单客户端发送超时不阻塞其他客户端与检测线程；
- 每 6 小时执行证据帧/报警保留清理，防磁盘膨胀；
- 优雅停机：关闭信号时停止检测线程并关库。
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .core.config import settings
from .core.logging import setup_logging
from .db import DATA_DIR, init_db
from .services import maintenance
from .services.pipeline import pipeline

setup_logging()
log = logging.getLogger("sv.main")

_BOOT_TS = time.time()


class WSManager:
    """单向广播：检测线程 → 所有界面客户端。

    背压策略：发给单个客户端的 send_text 限时 2s，超时即视为慢消费者
    并断开该连接——绝不让一个卡死的浏览器标签拖慢检测线程或别的客户端。
    """

    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients.add(ws)
        log.info("WS 客户端接入（当前 %d 个）", len(self.clients))

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.clients:
            self.clients.discard(ws)
            log.info("WS 客户端断开（剩余 %d 个）", len(self.clients))

    def broadcast(self, payload: dict) -> None:
        """线程安全：检测工作线程调用，投递到事件循环异步发送。"""
        if self.loop is None or not self.clients:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._send(payload), self.loop)
        except RuntimeError:
            pass

    async def _send(self, payload: dict) -> None:
        text = json.dumps(payload, ensure_ascii=False)
        for ws in list(self.clients):
            try:
                await asyncio.wait_for(ws.send_text(text), timeout=2.0)
            except Exception:
                self.disconnect(ws)

    async def close_all(self) -> None:
        for ws in list(self.clients):
            try:
                await ws.close()
            except Exception:
                pass
        self.clients.clear()


manager = WSManager()
app = FastAPI(title="SteelVision 带钢表面缺陷检测系统", version="0.7.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.exception("未捕获异常: %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": f"服务器内部错误：{type(exc).__name__}",
                 "path": request.url.path},
    )


app.include_router(router, prefix="/api")


@app.get("/api/health")
def health():
    """健康检查：值守脚本/看门狗/外部探针统一入口。"""
    disk = shutil.disk_usage(str(DATA_DIR))
    st = pipeline.status()
    db_ok = True
    try:
        from .db import SessionLocal
        with SessionLocal() as db:
            db.execute(__import__("sqlalchemy").text("SELECT 1"))
    except Exception:
        db_ok = False
    ok = db_ok and not st.get("last_error")
    return JSONResponse(status_code=200 if ok else 503, content={
        "ok": ok,
        "uptime_s": round(time.time() - _BOOT_TS, 1),
        "db_ok": db_ok,
        "disk_free_gb": round(disk.free / 1024 ** 3, 1),
        "ws_clients": len(manager.clients),
        "pipeline": {k: st.get(k) for k in
                     ("running", "frame_idx", "backend", "provider",
                      "last_error")},
    })


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()  # 心跳/占位，忽略客户端消息
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)


async def _retention_loop() -> None:
    """每 6 小时做一次保留清理；启动 30s 后先跑一次。"""
    await asyncio.sleep(30)
    while True:
        try:
            await asyncio.to_thread(maintenance.purge, settings.get())
        except Exception:
            log.exception("保留清理任务异常（下一周期重试）")
        await asyncio.sleep(6 * 3600)


@app.on_event("startup")
async def on_startup() -> None:
    init_db()
    manager.loop = asyncio.get_running_loop()
    pipeline.attach_broadcast(manager.broadcast)
    asyncio.create_task(_retention_loop())
    log.info("SteelVision 启动完成，数据目录: %s", DATA_DIR)


@app.on_event("shutdown")
async def on_shutdown() -> None:
    pipeline.stop()
    await manager.close_all()
    log.info("SteelVision 已优雅停机")


@app.get("/version")
def version():
    return {"app": "steel-vision", "version": "0.8.0",
            "protocol": "M3/M4 prototype"}


# 前端构建产物存在时由后端直接托管（生产形态：单端口 8000 出整套系统）。
# 托管策略（与 Frigate/ThingsBoard 生产部署一致）：
# - /assets 静态挂载，长缓存由浏览器处理；
# - 根路径与所有非 API 路径回退到 index.html，保证 /dashboard 等 SPA
#   深链接直接刷新、桌面壳与浏览器行为一致（此前整页挂载会导致 404）。
_frontend = __import__("pathlib").Path(__file__).resolve().parents[2] / "frontend" / "dist"
if (_frontend / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=str(_frontend / "assets")),
              name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        if full_path.startswith(("api/", "ws", "docs", "openapi.json",
                                 "redoc", "version")):
            raise HTTPException(404, "Not Found")
        candidate = _frontend / full_path
        if full_path and candidate.is_file() and ".." not in full_path:
            return FileResponse(str(candidate))
        return FileResponse(str(_frontend / "index.html"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
