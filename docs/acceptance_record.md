# SteelVision 验收记录（v0.8 · 2026-11-15）

本页记录 v0.8 交付前的实测证据，全部来自本机真实运行结果，非模拟数据。
每条结论都附可复现命令，评审时可现场重跑。

---

## 一、稳定性守夜测试

**命令**

```powershell
cd backend
py -3.12 scripts\soak_test.py --hours 0.1 --coil-minutes 2 --sample-seconds 30 --no-launch
```

**结果：PASS**

| 指标 | 实测 |
|---|---|
| 时长 / 卷数 / 样本 | 363 s / 3 卷 / 12 个样本 |
| 接口错误 | 0 |
| 流水线 last_error | 全程为空 |
| 后端进程 | 全程存活 |
| 数据库体积 | 0.05 MB，无异常膨胀 |
| 报告文件 | `backend/scripts/soak_report.json` / `.csv` |

**首跑即发现并修复的真实缺陷（重要）**

首轮守夜在报警触发时暴露 `AttributeError: module 'app.services.linkage' has no attribute 'notify'`：
`pipeline.py` 与 `api.py` 把 `linkage` **模块**当作单例实例调用，而实际入口是模块内的
`LinkManager` 实例。异常被记入 `last_error` 后，`/api/health` 随即将自身判定为不健康（503）。

修复：`pipeline._run` / `pipeline._finish` 改为 `from .linkage import linkage`；
`api.py` 同步改为导入单例。复测全程无 `last_error`、健康检查稳定 200。

> 说明：本轮为附加模式（`--no-launch`，后端已由看门狗托管），故 RSS 采样为 0 —— 这是脚本对
> 外部托管后端的已知限制。内存增长该项判定需在正式 72h 守夜（脚本自行拉起后端）时取得完整数据：
> `py -3.12 scripts\soak_test.py --hours 72 --coil-minutes 10`。

---

## 二、高可用部署

**开机自启**

计划任务注册在本机被权限策略拒绝（`Register-ScheduledTask` 与 `schtasks` 均返回 Access denied，
当前会话非管理员）。已落地等效免管理员方案：

- `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\SteelVisionBackend.cmd`
- `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\SteelVisionWatchdog.cmd`

登录即拉起后端 + 看门狗。`scripts\install_task.ps1` 已保留系统级注册能力：以管理员运行可升级为
`-AtStartup`（开机即启动，早于登录）。

**脚本修复**：`install_task.ps1` 原为 UTF-8 无 BOM 保存，Windows PowerShell 5.1 按系统 ANSI
代码页读取导致中文注释解析崩溃（连反引号转义被双字节字符吞掉）。已改为纯 ASCII 输出并加入
「无管理员自动降级到 AtLogOn」逻辑。

**看门狗**

每 10 s 巡检 `/api/health`，连续 3 次失败自动重启后端，日志 `backend/data/logs/watchdog.log`。

---

## 三、复核工作流闭环（演示卷 DEMO-1115-205444）

**取样**：`py -3.12 scripts\demo_coil.py`（NEU-DET 测试集真实缺陷样本，30 s）

**批复核**：`py -3.12 scripts\review_demo.py --coil DEMO-1115-205444`

复核口径：置信度 ≥ 0.60 判确认、< 0.30 判误报剔除、中间带按缺陷 ID 确定性抽样（可复现）。

| 指标 | 复核前 | 复核后 |
|---|---|---|
| 待复核 | 173 | 0 |
| 已确认 | 0 | 96 |
| 误报剔除 | 0 | 77 |
| 有效缺陷 | 173 | 96 |
| 有效密度 | 3.45 个/米 | **1.92 个/米** |
| 判级 | **C**（复检或降级处理） | **B**（放行 / 常规抽检） |

**业务含义**：误报剔除 44% 后，该卷由「阻断放行」转为「放行」——复核工作流直接改变了
处置决策，而非仅做记录。录屏演示时可用 `--reset` 把卷重置回 173 条待复核，再在界面上
逐条标注，观察报表页密度与判级实时翻转。

---

## 四、算法监测绿框实时叠加

工业视觉的标准做法：检测框由上位机矢量绘制，不烧录进视频流（避免重复编码、保证任意分辨率清晰）。

**实现**

- 后端：实况帧回传原始图 + 本帧检测框坐标 + 帧宽高；证据帧仍烧录绿框（供人工复核与审计留痕）。
- 前端：监控页画面叠加 SVG 层，绿框随帧实时变动，每框带标签显示「类别 置信度」，
  坐标 1:1 映射帧像素（`viewBox` 直通帧尺寸，非缩放描边）。

**实测**：`py -3.12 scripts\verify_hmi.py --seconds 25`

| 检查项 | 结果 |
|---|---|
| WS 帧样本 | 42 个 |
| 携带帧尺寸（w/h） | 42 个 |
| 携带检测框（events） | 9 个 |
| 样例框 | `patches conf=0.3794 (145.4,130.4)→(199.8,200.0)` |
| 页面渲染 | 截图 `backend/scripts/shots/dashboard-green-box.png` (1680×960)，绿色采样点 159 个 |

---

## 五、客户端交付形态（PyQt5 桌面壳）

- 依赖：`PyQt5 5.15.11` + `PyQtWebEngine 5.15.7`（`desktop/requirements-desktop.txt`）
- 形态：`QWebEngineView` 全屏壳，内嵌**同一套 HMI**（单端口 8000 出整套系统），与浏览器零差异
- 窗口标题：`SteelVision · 带钢表面缺陷检测系统 v0.8`

**F11 全屏切换实测**：`py -3.12 desktop\verify_shell.py` → **PASS**

| 步骤 | 窗口尺寸 |
|---|---|
| 起点（常规） | 1135 × 677 |
| 按 F11 | **1707 × 1067（全屏）** |
| 再按 F11 | 1135 × 677（还原） |

屏幕分辨率 1707×1067，双向切换均正确。验证脚本修正了两处自身缺陷（浏览器页面标题与桌面壳
重名导致误命中、最小化窗口坐标失真），现为可复用的一键验收工具。

---

## 六、Web 端路由与静态托管

生产托管采用与 Frigate / ThingsBoard 一致的范式：`/assets` 静态挂载 + 显式 SPA 回退路由。

早期整页 `StaticFiles(html=True)` 挂载会导致 `/dashboard` 等深链接整页刷新 404，已修复。

| 检查项 | 结果 |
|---|---|
| `/`、`/dashboard`、`/review`、`/reports`、`/alarms`、`/settings` | 全部 HTTP 200 |
| 静态资源 JS / CSS | 200（1.17 MB / 14.3 KB） |
| `/api/nonexistent` | 404（未被回退路由吞掉） |
| 六个核心 API | 全部 200 |

---

## 复现清单（评审现场可按序执行）

```powershell
# 0. 后端（未由启动项拉起时）
cd backend; py -3.12 -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 1. 稳定性（6 分钟冒烟 / 正式 72h）
py -3.12 scripts\soak_test.py --hours 0.1 --coil-minutes 2 --no-launch
py -3.12 scripts\soak_test.py --hours 72 --coil-minutes 10

# 2. 演示卷 + 复核闭环
py -3.12 scripts\demo_coil.py
py -3.12 scripts\review_demo.py

# 3. 绿框叠加核验（自动截图）
py -3.12 scripts\verify_hmi.py

# 4. 桌面壳 + F11
py -3.12 ..\desktop\shell.py
py -3.12 ..\desktop\verify_shell.py
```
