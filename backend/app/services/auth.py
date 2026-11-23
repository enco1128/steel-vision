"""会话鉴权：内存令牌（12h 有效）。

定位为"原型级角色隔离"（admin / operator / viewer），
生产部署时替换为 JWT + 持久化会话（接口形态保持不变）。
"""
from __future__ import annotations

import hashlib
import secrets
import time

_SESSIONS: dict[str, dict] = {}
_TTL = 12 * 3600


def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()


def login(db, username: str, password: str):
    from ..models import User

    user = db.query(User).filter(User.username == username).first()
    if not user or user.password != hash_pw(password):
        return None, None
    token = secrets.token_hex(16)
    _SESSIONS[token] = {"username": user.username, "role": user.role, "ts": time.time()}
    return token, {"username": user.username, "role": user.role}


def verify(token: str | None) -> dict | None:
    sess = _SESSIONS.get(token or "")
    if not sess:
        return None
    if time.time() - sess["ts"] > _TTL:
        _SESSIONS.pop(token or "", None)
        return None
    return sess


def logout(token: str | None) -> None:
    _SESSIONS.pop(token or "", None)
