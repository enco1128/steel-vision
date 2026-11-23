/**
 * 演示模式：纯静态部署（GitHub Pages）下的离线数据回放层。
 *
 * 构建时设置 VITE_DEMO=1 启用：api() 全部走本地快照（snapshot.json），
 * WebSocket 用录制的帧序列循环回放，复核/报警确认等写操作在内存中生效，
 * 刷新后恢复初始快照（适合甲方浏览演示，不产生任何服务端状态）。
 *
 * 快照由 backend/scripts/export_snapshot.py 从真实运行系统导出。
 */
import { ui } from './store'

let SNAP = null
let ready = null

/* 内存态：可写的部分从快照深拷贝，写操作只改这里 */
const state = {
  coils: [], defects: [], alarms: [], settings: {}, modelInfo: {},
  frames: [], frameMeta: {},
}

function deep(o) { return JSON.parse(JSON.stringify(o)) }

export function isDemo() { return true }

/* 证据帧地址：演示构建用快照内嵌 dataURL，正常构建走后端图片接口 */
export function evidenceUrl(defect) {
  if (!defect) return ''
  const url = state.evidence?.[defect.id]
  return url || (defect.evidence_path ? `/api/evidence/${defect.id}` : '')
}

export async function loadSnapshot() {
  if (ready) return ready
  ready = (async () => {
    const base = import.meta.env.BASE_URL || '/'
    const res = await fetch(`${base}demo/snapshot.json`)
    if (!res.ok) throw new Error(`快照加载失败：${res.status}`)
    SNAP = await res.json()
    state.coils = deep(SNAP.coils || [])
    state.defects = deep(SNAP.defects || [])
    state.alarms = deep(SNAP.alarms || [])
    state.settings = deep(SNAP.settings || {})
    state.modelInfo = deep(SNAP.model_info || {})
    state.frames = SNAP.frames || []
    state.frameMeta = SNAP.frame_meta || {}
    /* 证据帧以 dataURL 形式内嵌（去敏后仅演示样本的标注帧） */
    state.evidence = SNAP.evidence || {}
  })()
  return ready
}

/* ---------------------------------------------------------------- 报表复算
 * 口径与 backend/app/services/reports.py::coil_report 完全一致 */
function coilReport(coilId) {
  const coil = state.coils.find(c => c.id === coilId)
  if (!coil) return null
  const defects = state.defects.filter(d => d.coil_id === coilId)
  const counts = {}
  for (const d of defects) counts[d.cls_name] = (counts[d.cls_name] || 0) + 1
  const confirmed = defects.filter(d => d.review_status === 'confirmed').length
  const falseAlarms = defects.filter(d => d.review_status === 'false_alarm').length
  const pending = defects.length - confirmed - falseAlarms
  const effective = defects.length - falseAlarms
  const length = Number(coil.length_m || 0)
  const density = length > 0 ? Math.round(effective / length * 100) / 100 : 0
  const th = Number((state.settings.alarms || {}).density_per_m ?? 2.0)
  let grade, advice
  if (effective === 0) { grade = 'A'; advice = '放行（未检出有效缺陷）' }
  else if (density <= th) { grade = 'B'; advice = '放行 / 常规抽检' }
  else { grade = 'C'; advice = '复检或降级处理' }
  return {
    coil_id: coil.id, coil_no: coil.coil_no,
    start_ts: coil.start_ts, end_ts: coil.end_ts, status: coil.status,
    source: coil.source, frames_total: coil.frames_total, length_m: length,
    defect_total: defects.length, effective_total: effective,
    confirmed, false_alarms: falseAlarms, pending, counts,
    density_per_m: density, threshold_per_m: th,
    duration_sec: 0, grade, advice,
  }
}

function csvEscape(v) { return String(v ?? '').replace(/"/g, '""') }

function buildCsv(coilId) {
  const defects = state.defects.filter(d => d.coil_id === coilId)
  const head = '缺陷ID,时间,帧号,类别,置信度,X1,Y1,X2,Y2,复核状态,复核备注,证据帧'
  const rows = defects.map(d => [d.id, d.ts, d.frame_idx, d.cls_name,
    d.conf.toFixed(4), d.x1.toFixed(1), d.y1.toFixed(1), d.x2.toFixed(1), d.y2.toFixed(1),
    d.review_status, (d.review_note || '').replace(/,/g, '；'), d.evidence_path ? '(演示)' : '-'].join(','))
  return '\ufeff' + [head, ...rows].join('\r\n')
}

/* ---------------------------------------------------------------- api 模拟 */
function jsonBody(opts) {
  try { return opts.body ? JSON.parse(opts.body) : {} } catch { return {} }
}

function ok(data) { return deep(data) }

export async function demoApi(path, opts = {}) {
  await loadSnapshot()
  const method = (opts.method || 'GET').toUpperCase()
  const url = new URL(path, 'http://x')
  const p = url.pathname
  const q = url.searchParams

  let m
  if (p === '/api/auth/login') {
    const b = jsonBody(opts)
    const users = { admin: 'admin123', operator: 'operator123', viewer: 'viewer123' }
    if (users[b.username] !== b.password) throw new Error('用户名或密码错误（演示环境）')
    const role = b.username
    return { token: `demo-${b.username}`, user: { username: b.username, role } }
  }
  if (p === '/api/alarms') {
    let rows = state.alarms
    if (q.get('only_unacked') === 'true') rows = rows.filter(a => !a.acked)
    const lim = Number(q.get('limit') || 100)
    return ok(rows.slice(0, lim))
  }
  if ((m = p.match(/^\/api\/alarms\/(\d+)\/ack$/)) && method === 'POST') {
    const a = state.alarms.find(x => x.id === Number(m[1]))
    if (a) { a.acked = true; a.ack_ts = new Date().toISOString().slice(0, 19).replace('T', ' ') }
    return { ok: true }
  }
  if (p === '/api/coils') return ok(state.coils)
  if ((m = p.match(/^\/api\/coils\/(\d+)\/defects$/))) {
    return ok(state.defects.filter(d => d.coil_id === Number(m[1])))
  }
  if ((m = p.match(/^\/api\/defects\/(\d+)\/review$/)) && method === 'POST') {
    const d = state.defects.find(x => x.id === Number(m[1]))
    const b = jsonBody(opts)
    if (d) { d.review_status = b.status || d.review_status; d.review_note = b.note || '' }
    return { ok: true }
  }
  if ((m = p.match(/^\/api\/reports\/coil\/(\d+)$/))) {
    const rep = coilReport(Number(m[1]))
    if (!rep) throw new Error('卷不存在')
    return rep
  }
  if ((m = p.match(/^\/api\/reports\/coil\/(\d+)\/export\.(csv|html)$/))) {
    const id = Number(m[1])
    if (m[2] === 'csv') return buildCsv(id)
    return '<h3>演示环境不提供 HTML 报告下载，请在本机运行系统导出。</h3>'
  }
  if ((m = p.match(/^\/api\/evidence\/(\d+)$/))) {
    return state.evidence[Number(m[1])] || ''
  }
  if (p === '/api/system/status') {
    return {
      pipeline: { running: false, backend: state.modelInfo.backend || 'onnxruntime',
        provider: state.modelInfo.provider || 'CPU', last_error: '' },
      model_exists: true, model_path: '(演示快照)',
      source_presets: ['demo/neu_det/test'], class_names: state.settings.class_names || [],
    }
  }
  if (p === '/api/settings' && method === 'GET') return ok(state.settings)
  if (p === '/api/settings' && method === 'PUT') {
    const b = jsonBody(opts)
    Object.assign(state.settings, b)
    return ok(state.settings)
  }
  if (p === '/api/model/info') return ok(state.modelInfo)
  if (p === '/api/model/reload') return { ok: true, note: '演示环境已模拟热切换' }
  if (p === '/api/linkage/test') return { ok: true, driver: 'dryrun' }
  if (p === '/api/pipeline/start') {
    playFrames()
    return { running: true }
  }
  if (p === '/api/pipeline/stop') { stopFrames(); return { running: false } }

  throw new Error(`演示环境未提供该接口：${p}`)
}

/* ---------------------------------------------------------------- WS 回放 */
let playTimer = null
let frameIdx = 0
let loopN = 0

function playFrames() {
  if (playTimer) return
  frameIdx = 0
  ui.wsOk = true
  playTimer = setInterval(() => {
    if (!state.frames.length) return
    const seq = state.frames
    const f = seq[frameIdx % seq.length]
    frameIdx += 1
    if (frameIdx % seq.length === 0) loopN += 1
    const meta = state.frameMeta || {}
    ui.frame = f
    ui.frameW = meta.w || 960
    ui.frameH = meta.h || 540
    ui.dets = (meta.events_by_idx?.[(frameIdx - 1) % seq.length]) || []
    ui.fps = 10
    const ev = ui.dets
    if (ev.length) {
      ui.events.unshift(...ev.slice().reverse())
      if (ui.events.length > 200) ui.events.length = 200
    }
    ui.coil = { id: 0, no: meta.coil_no || 'DEMO-COIL', count: meta.defect_count || 0, idx: frameIdx }
  }, 100)
}

function stopFrames() {
  clearInterval(playTimer)
  playTimer = null
}

/* 无后端也保持顶栏「实时链路」为 ONLINE，体现演示形态 */
export async function startFramePlayback() {
  ui.wsOk = true
  await loadSnapshot()
  if (!state.frames.length) return
  /* 默认循环回放最后一卷的帧（甲方打开即可看到实时画面） */
  playFrames()
}
