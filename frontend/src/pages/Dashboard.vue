<template>
  <div class="dash">
    <div class="toolbar">
      <span class="field-label">卷号</span>
      <input v-model="coilNo" class="input mono" style="width: 150px" placeholder="留空自动生成" />
      <span class="field-label">数据源</span>
      <select v-model="source" class="input" style="max-width: 360px">
        <option value="">按系统配置（留空=合成帧）</option>
        <option v-for="p in presets" :key="p" :value="p">{{ p }}</option>
      </select>
      <button class="btn primary" :disabled="running" @click="start">开始检测</button>
      <button class="btn danger" :disabled="!running" @click="stop">结束本卷</button>
      <span class="spacer"></span>
      <span v-if="msg" class="msg-line">{{ msg }}</span>
      <span :class="['tag', running ? 'run' : 'idle']">{{ running ? '检测运行中' : '系统待命' }}</span>
    </div>

    <div class="kpis">
      <div :class="['kpi', running ? 'ok' : '']">
        <small>运行状态</small>
        <b>{{ running ? 'RUN' : 'IDLE' }}</b>
        <div class="state-line">
          <span :class="['led', running ? 'on' : '']"></span>
          <span>{{ running ? `本卷帧数 ${ui.coil.idx}` : '等待开始指令' }}</span>
        </div>
      </div>
      <div :class="['kpi', countPct > 66 ? 'bad' : (countPct > 33 ? 'warn' : '')]">
        <small>本卷缺陷累计（阈值 {{ alarmThreshold }}）</small>
        <b>{{ ui.coil.count }}<span class="unit">个</span></b>
        <div class="gauge-bar"><i :style="{ width: countPct + '%' }" :class="countPct > 66 ? 'c' : (countPct > 33 ? 'b' : '')"></i></div>
      </div>
      <div class="kpi info">
        <small>实时帧率</small>
        <b>{{ ui.fps }}<span class="unit">fps</span></b>
        <div class="gauge-bar"><i class="i" :style="{ width: Math.min(ui.fps * 5, 100) + '%' }"></i></div>
      </div>
      <div class="kpi">
        <small>推理后端</small>
        <b style="font-size: 14px; margin-top: 8px; word-break: break-all">{{ backend || '未初始化' }}</b>
        <div class="state-line"><span class="dim">{{ tiling ? '大图切片已启用' : '整图推理' }}</span></div>
      </div>
    </div>

    <div class="dash-main">
      <div class="canvas-col">
        <div class="canvas-wrap">
          <span class="canvas-tag">CAM-PRIMARY · LIVE</span>
          <div v-if="ui.frame" class="canvas-stage">
            <img :src="ui.frame" alt="实时检测画面" />
            <svg
              v-if="ui.frameW && ui.frameH && ui.dets.length"
              class="det-overlay"
              :viewBox="`0 0 ${ui.frameW} ${ui.frameH}`"
              preserveAspectRatio="xMidYMid meet"
            >
              <g v-for="d in ui.dets" :key="d.id">
                <rect :x="d.x1" :y="d.y1" :width="Math.max(d.x2 - d.x1, 1)" :height="Math.max(d.y2 - d.y1, 1)"
                  class="det-box" />
                <g :transform="`translate(${d.x1}, ${Math.max(d.y1 - 4, 14)})`">
                  <rect :width="labelWidth(d)" height="16" x="0" y="-14" class="det-label-bg" />
                  <text x="4" y="-2" class="det-label-text">{{ d.cls }} {{ d.conf.toFixed(2) }}</text>
                </g>
              </g>
            </svg>
          </div>
          <div v-else class="placeholder">
            无画面输入<br />
            点击「开始检测」；数据源未配置时使用合成帧冒烟运行
          </div>
          <div v-if="ui.alarm" :class="['alarm-banner', { critical: ui.alarm.level === 'critical' }]">
            <span>[{{ levelLabel[ui.alarm.level] || ui.alarm.level }}] {{ ui.alarm.message }}</span>
            <button class="btn tiny" @click="ackLast">确认</button>
          </div>
          <div class="hud">
            <span>卷号<b>{{ ui.coil.no || '—' }}</b></span>
            <span>帧号<b>{{ ui.coil.idx }}</b></span>
            <span>缺陷<b>{{ ui.coil.count }}</b></span>
            <span>链路<b :class="ui.wsOk ? '' : 'pri-critical'">{{ ui.wsOk ? 'OK' : 'LOST' }}</b></span>
          </div>
        </div>

        <div class="process-strip">
          <div :class="['pnode', running ? 'on' : '']">
            <span class="pdot"></span><span class="plabel">图像采集</span>
          </div>
          <div :class="['pipe', running ? 'on' : '']"></div>
          <div :class="['pnode', running ? 'on' : '']">
            <span class="pdot"></span><span class="plabel">缺陷推理</span>
          </div>
          <div :class="['pipe', running ? 'on' : '']"></div>
          <div :class="['pnode', running ? 'on' : '']">
            <span class="pdot"></span><span class="plabel">事件落库</span>
          </div>
          <div :class="['pipe', running ? 'on' : '']"></div>
          <div :class="['pnode', running && !ui.alarm ? 'on' : (ui.alarm ? 'fault' : '')]">
            <span class="pdot"></span><span class="plabel">报警引擎</span>
          </div>
          <div :class="['pipe', ui.wsOk ? 'on' : '']"></div>
          <div :class="['pnode', ui.wsOk ? 'on' : 'fault']">
            <span class="pdot"></span><span class="plabel">HMI 推送</span>
          </div>
        </div>
      </div>

      <aside class="stream">
        <div class="stream-hd">
          实时缺陷事件
          <span class="sub">最新在前 · {{ ui.events.length }} 条</span>
        </div>
        <div class="stream-scroll">
          <div v-for="e in ui.events" :key="e.id" :class="['stream-row', e.conf >= 0.7 ? 'conf-hi' : '']">
            <span class="t">{{ e.ts.slice(11) }}</span>
            <span class="c">{{ e.cls }}</span>
            <span class="p">{{ e.conf.toFixed(3) }}</span>
          </div>
          <div v-if="!ui.events.length" class="stream-empty">暂无缺陷事件</div>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api'
import { ui } from '../store'

const running = ref(false)
const coilNo = ref('')
const source = ref('')
const presets = ref([])
const backend = ref('')
const tiling = ref(false)
const alarmThreshold = ref(8)
const msg = ref('')
let timer = null

const levelLabel = { info: '提示', warn: '警告', critical: '临界' }
const countPct = computed(() =>
  Math.min((ui.coil.count / Math.max(alarmThreshold.value, 1)) * 100, 100))

/* SVG 标签底板宽度：等宽字体近似 7.8px/字符（12px 字号，含 8px 内边距） */
function labelWidth(d) {
  const text = `${d.cls} ${d.conf.toFixed(2)}`
  return Math.max(52, Math.round(text.length * 7.8 + 8))
}

async function refresh() {
  try {
    const st = await api('/api/system/status')
    running.value = !!st.pipeline.running
    presets.value = st.source_presets || []
    tiling.value = !!st.pipeline.tiling
    backend.value = st.pipeline.backend
      ? `${st.pipeline.backend} / ${st.pipeline.provider}`
      : ''
  } catch { /* 后端未就绪，3 秒后自动重试 */ }
  try {
    const cfg = await api('/api/settings')
    alarmThreshold.value = cfg.alarms?.min_defects_per_coil || 8
  } catch { /* 非管理员不可读设置时保持默认 */ }
}

onMounted(() => { refresh(); timer = setInterval(refresh, 3000) })
onUnmounted(() => clearInterval(timer))

async function start() {
  msg.value = ''
  try {
    await api('/api/pipeline/start', {
      method: 'POST',
      body: JSON.stringify({ coil_no: coilNo.value, source: source.value }),
    })
    running.value = true
    ui.events = []
  } catch (e) { msg.value = e.message }
}

async function stop() {
  msg.value = ''
  try {
    await api('/api/pipeline/stop', { method: 'POST' })
  } catch (e) { msg.value = e.message }
}

function ackLast() {
  if (!ui.alarm) return
  api(`/api/alarms/${ui.alarm.id}/ack`, { method: 'POST' })
    .then(() => { ui.alarm = null })
    .catch((e) => { msg.value = e.message })
}
</script>
