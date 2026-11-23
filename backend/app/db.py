"""SQLite 数据层：引擎、会话、目录（证据帧库）与初始化种子。"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATA_DIR = Path(os.environ.get(
    "SV_DATA", str(Path(__file__).resolve().parents[1] / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
FRAME_DIR = DATA_DIR / "frames"
FRAME_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "steel_vision.db"
engine = create_engine(f"sqlite:///{DB_PATH}",
                       connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def init_db() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL;")  # 读写并行（界面查询不阻塞采集写入）
    _seed_users()


def _seed_users() -> None:
    from .models import User
    from .services.auth import hash_pw

    with SessionLocal() as db:
        if db.query(User).first():
            return
        db.add_all([
            User(username="admin", password=hash_pw("admin123"), role="admin"),
            User(username="operator", password=hash_pw("operator123"), role="operator"),
            User(username="viewer", password=hash_pw("viewer123"), role="viewer"),
        ])
        db.commit()
