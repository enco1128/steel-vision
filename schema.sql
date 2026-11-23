-- SteelVision v0.5 数据库结构（SQLite；由 SQLAlchemy 自动建表，此文件用于留档与外部工具对接）
-- 归档范式：一"卷"(coil) = 一次连续检测周期；缺陷/报警/复核均挂载在卷下。

CREATE TABLE IF NOT EXISTS users (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  password TEXT NOT NULL,              -- sha256（原型级；生产替换为加盐哈希）
  role     TEXT DEFAULT 'viewer'       -- admin / operator / viewer
);

CREATE TABLE IF NOT EXISTS coils (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  coil_no       TEXT NOT NULL UNIQUE,  -- 卷号（业务主键，可对接产线 MES 编号）
  start_ts      TEXT DEFAULT '',
  end_ts        TEXT DEFAULT '',
  source        TEXT DEFAULT '',       -- 数据源：视频/图像目录/相机（预留）
  frames_total  INTEGER DEFAULT 0,
  length_m      REAL DEFAULT 0,        -- 带钢长度（按 meters_per_frame 标定）
  defect_count  INTEGER DEFAULT 0,
  quality_grade TEXT DEFAULT '',       -- A / B / C（报表判级）
  status        TEXT DEFAULT 'running' -- running / closed
);

CREATE TABLE IF NOT EXISTS defects (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  coil_id       INTEGER NOT NULL REFERENCES coils(id),
  ts            TEXT DEFAULT '',
  frame_idx     INTEGER DEFAULT 0,
  class_id      INTEGER DEFAULT 0,
  cls_name      TEXT DEFAULT '',
  conf          REAL DEFAULT 0,
  x1 REAL, y1 REAL, x2 REAL, y2 REAL,  -- 帧内像素坐标（卷内定位）
  evidence_path TEXT DEFAULT '',       -- 证据帧 JPG（低于证据阈值时为空）
  review_status TEXT DEFAULT 'pending',-- pending / confirmed / false_alarm
  review_note   TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_defects_coil ON defects (coil_id);

CREATE TABLE IF NOT EXISTS alarms (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  coil_id  INTEGER REFERENCES coils(id),
  rule     TEXT DEFAULT '',            -- priority:<类> / count / grade
  level    TEXT DEFAULT 'warn',        -- info / warn / critical
  message  TEXT DEFAULT '',
  ts       TEXT DEFAULT '',
  acked    INTEGER DEFAULT 0,          -- 确认工作流（对齐 ThingsBoard 范式）
  acked_by TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_alarms_coil ON alarms (coil_id);
