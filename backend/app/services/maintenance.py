"""数据保留清理：证据帧与已确认报警按保留期回收，防 72h+ 连续运行磁盘膨胀。

策略（可在 config.json / 设置页调整 retention.evidence_days）：
- 超过保留期的证据帧 jpg 删除，缺陷记录保留但清空 evidence_path（统计数据完整）；
- 超过保留期且已确认的报警记录删除；
- 由 main.py 后台任务每 6 小时执行一次，启动时也执行一次。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

from ..db import SessionLocal
from ..models import Alarm, Defect

log = logging.getLogger("sv.maintenance")


def purge(cfg: dict) -> dict:
    days = float((cfg.get("retention") or {}).get("evidence_days", 30))
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    files = 0
    alarms = 0
    with SessionLocal() as db:
        rows = (db.query(Defect)
                .filter(Defect.evidence_path != "", Defect.ts < cutoff).all())
        for d in rows:
            p = Path(d.evidence_path)
            try:
                if p.exists():
                    p.unlink()
                    files += 1
            except OSError:
                pass
            d.evidence_path = ""
        old_alarms = (db.query(Alarm)
                      .filter(Alarm.acked == 1, Alarm.ts < cutoff).all())
        alarms = len(old_alarms)
        for a in old_alarms:
            db.delete(a)
        db.commit()

    if files or alarms:
        log.info("保留清理：删除证据帧 %d 张、已确认报警 %d 条（保留 %.0f 天）",
                 files, alarms, days)
    return {"files": files, "alarms": alarms, "days": days}
