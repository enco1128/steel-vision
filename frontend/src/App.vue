<template>
  <div class="app">
    <header class="topbar">
      <div class="brand">
        <span class="brand-mark">SV</span>
        <div>
          <div class="brand-title">SteelVision 带钢表面缺陷检测系统</div>
          <div class="brand-sub">M3/M4 产线 · 工业级 HMI · v0.8</div>
        </div>
      </div>

      <div class="status-cluster">
        <div class="status-item">
          <span :class="['led', ui.wsOk ? 'on' : 'bad', ui.wsOk ? '' : 'blink']"></span>
          实时链路
          <b>{{ ui.wsOk ? 'ONLINE' : 'LOST' }}</b>
        </div>
        <div class="status-item">
          <span :class="['led', pipe.running ? 'on' : '']"></span>
          检测
          <b>{{ pipe.running ? 'RUN' : 'IDLE' }}</b>
        </div>
        <div class="status-item">
          <span class="muted">帧率</span>
          <b>{{ ui.fps }}</b>
        </div>
        <div class="status-item">
          <span class="muted">推理</span>
          <b>{{ pipe.backend ? `${pipe.backend}/${pipe.provider}` : '—' }}</b>
        </div>
        <div class="status-item">
          <button
            class="btn tiny"
            :title="theme === 'dark' ? '切换到浅色主题' : '切换到深色主题'"
            @click="toggleTheme"
          >
            {{ theme === 'dark' ? '浅色' : '深色' }}
          </button>
        </div>
        <div class="top-clock">{{ clock }}</div>
      </div>
    </header>

    <nav class="side">
      <div class="nav-section">生产监控</div>
      <RouterLink to="/dashboard" class="nav-item" active-class="active">运行监控</RouterLink>
      <RouterLink to="/review" class="nav-item" active-class="active">缺陷复核</RouterLink>
      <div class="nav-section">质量与报警</div>
      <RouterLink to="/reports" class="nav-item" active-class="active">统计报表</RouterLink>
      <RouterLink to="/alarms" class="nav-item" active-class="active">
        报警中心
        <span :class="['nav-count', unacked ? '' : 'zero']">{{ unacked }}</span>
      </RouterLink>
      <div class="nav-section">系统</div>
      <RouterLink to="/settings" class="nav-item" active-class="active">系统设置</RouterLink>
    </nav>

    <main class="content">
      <RouterView />
    </main>

    <footer class="statusbar" :class="{ alert: counts.critical > 0 }">
      <div class="left alarm-summary">
        <span class="muted">未确认报警</span>
        <span class="cnt pri-critical"><i></i>临界 <b>{{ counts.critical }}</b></span>
        <span class="cnt pri-warn"><i></i>警告 <b>{{ counts.warn }}</b></span>
        <span class="cnt pri-info"><i></i>提示 <b>{{ counts.info }}</b></span>
      </div>
      <div class="right">
        <span v-if="ui.alarm" class="pri-critical">
          最近报警：{{ ui.alarm.message }}
        </span>
        <span class="mono" :class="ui.wsOk ? '' : 'pri-critical'">{{ ui.wsOk ? 'WS OK' : 'WS OFF' }}</span>
      </div>
    </footer>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { RouterLink, RouterView } from 'vue-router'
import { api } from './api'
import { ui } from './store'

const clock = ref('')
const pipe = reactive({ running: false, backend: '', provider: '' })
const counts = reactive({ critical: 0, warn: 0, info: 0 })
let timer = null
let poll = null

/* 主题：默认浅色（录制形态），可切 dark 并记忆在 localStorage */
const THEME_KEY = 'sv_theme'
const theme = ref(localStorage.getItem(THEME_KEY) === 'dark' ? 'dark' : 'light')

function applyTheme(t) {
  theme.value = t
  document.documentElement.dataset.theme = t
  localStorage.setItem(THEME_KEY, t)
  window.dispatchEvent(new Event('sv-theme'))
}

function toggleTheme() {
  applyTheme(theme.value === 'dark' ? 'light' : 'dark')
}

const unacked = computed(() => counts.critical + counts.warn + counts.info)

function tick() {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  clock.value = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

async function refreshAlarmCounts() {
  try {
    const rows = await api('/api/alarms?only_unacked=true&limit=500')
    counts.critical = rows.filter(a => a.level === 'critical').length
    counts.warn = rows.filter(a => a.level === 'warn').length
    counts.info = rows.filter(a => a.level === 'info').length
  } catch { /* 后端未就绪时保持原值 */ }
}

async function refreshPipeline() {
  try {
    const st = await api('/api/system/status')
    pipe.running = !!st.pipeline.running
    pipe.backend = st.pipeline.backend || ''
    pipe.provider = st.pipeline.provider || ''
  } catch { /* 静默重试 */ }
}

watch(() => ui.alarms.length, refreshAlarmCounts)

onMounted(() => {
  document.documentElement.dataset.theme = theme.value
  tick()
  timer = setInterval(tick, 1000)
  refreshPipeline()
  refreshAlarmCounts()
  poll = setInterval(() => { refreshPipeline(); refreshAlarmCounts() }, 10000)
})
onUnmounted(() => { clearInterval(timer); clearInterval(poll) })
</script>
