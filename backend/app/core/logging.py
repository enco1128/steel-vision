"""日志装配：控制台 + RotatingFileHandler 落盘（data/logs/app.log，10MB×5 轮转）。

工业现场要求：长时间无人值守时日志既不能爆盘，也要保留足够窗口定位问题，
因此统一走轮转文件；uvicorn 的访问/错误日志一并落盘。
"""
from __future__ import annotations

import logging
import logging.handlers

from ..db import DATA_DIR


def setup_logging(level: str = "INFO") -> None:
    log_dir = DATA_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S")

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "app.log", maxBytes=10 * 1024 * 1024, backupCount=5,
        encoding="utf-8")
    file_handler.setFormatter(fmt)

    console = logging.StreamHandler()
    console.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    if not any(isinstance(h, logging.handlers.RotatingFileHandler)
               for h in root.handlers):
        root.addHandler(file_handler)
        root.addHandler(console)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.setLevel(level)
        if file_handler not in lg.handlers:
            lg.addHandler(file_handler)
