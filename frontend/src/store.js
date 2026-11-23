import { reactive } from 'vue'

export const ui = reactive({
  wsOk: false,
  frame: '',
  frameW: 0,
  frameH: 0,
  dets: [],
  events: [],
  alarm: null,
  alarms: [],
  coil: { id: null, no: '', count: 0, idx: 0 },
  fps: 0,
})

let ws = null
let retryTimer = null
let heartbeat = null
let retryDelay = 1000
let frameCount = 0
let fpsTimer = null

function wsUrl() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/ws`
}

export function connectWS() {
  if (ws && ws.readyState <= 1) return
  try {
    ws = new WebSocket(wsUrl())
  } catch {
    scheduleRetry()
    return
  }
  ws.onopen = () => {
    ui.wsOk = true
    retryDelay = 1000
    /* 心跳：25s 应用层 ping，穿透现场代理的空闲断连 */
    clearInterval(heartbeat)
    heartbeat = setInterval(() => {
      try { ws.send('ping') } catch { /* onclose 会接管重连 */ }
    }, 25000)
  }
  ws.onmessage = (ev) => {
    let m
    try { m = JSON.parse(ev.data) } catch { return }
    if (m.type === 'frame') {
      ui.frame = 'data:image/jpeg;base64,' + m.jpeg
      ui.frameW = m.w || 0
      ui.frameH = m.h || 0
      ui.dets = m.events || []
      ui.coil = { id: m.coil_id, no: m.coil_no, count: m.defect_count, idx: m.frame_idx }
      frameCount += 1
      if (m.events && m.events.length) {
        ui.events.unshift(...m.events.slice().reverse())
        if (ui.events.length > 200) ui.events.length = 200
      }
    } else if (m.type === 'alarm') {
      ui.alarm = m.alarm
      ui.alarms.unshift(m.alarm)
      if (ui.alarms.length > 50) ui.alarms.length = 50
    } else if (m.type === 'coil_closed') {
      ui.alarm = null
    }
  }
  ws.onclose = () => {
    ui.wsOk = false
    clearInterval(heartbeat)
    ws = null
    scheduleRetry()
  }
  ws.onerror = () => {
    try { ws.close() } catch { /* 已被 close 处理 */ }
  }
}

function scheduleRetry() {
  clearTimeout(retryTimer)
  retryTimer = setTimeout(connectWS, retryDelay)
  retryDelay = Math.min(retryDelay * 2, 15000)  /* 1s→15s 指数退避，网络抖动不闪断 */
}

clearInterval(fpsTimer)
fpsTimer = setInterval(() => {
  ui.fps = frameCount
  frameCount = 0
}, 1000)
