<template>
  <div>
    <div class="toolbar">
      <span class="field-label">卷</span>
      <select v-model="coilId" class="input" style="max-width: 340px">
        <option v-if="!coils.length" :value="null">暂无卷记录</option>
        <option v-for="c in coils" :key="c.id" :value="c.id">
          {{ c.coil_no }}（{{ c.status === 'running' ? '检测中' : '已结束' }}）
        </option>
      </select>
      <button class="btn" @click="loadReport">刷新</button>
      <a v-if="report" class="btn" :href="`/api/reports/coil/${coilId}/export.csv`" target="_blank">导出缺陷 CSV</a>
      <a v-if="report" class="btn" :href="`/api/reports/coil/${coilId}/export.html`" target="_blank">检查报告 HTML</a>
      <span class="spacer"></span>
      <span v-if="msg" class="msg-line">{{ msg }}</span>
    </div>

    <template v-if="report">
      <div class="kpis">
        <div class="kpi info">
          <small>检出缺陷</small>
          <b>{{ report.defect_total }}<span class="unit">个</span></b>
        </div>
        <div class="kpi ok">
          <small>复核确认</small>
          <b>{{ report.confirmed }}<span class="unit">个</span></b>
        </div>
        <div class="kpi" :class="report.false_alarms > 0 ? 'warn' : ''">
          <small>误报剔除</small>
          <b>{{ report.false_alarms }}<span class="unit">个</span></b>
        </div>
        <div class="kpi" :class="gradeKpiClass">
          <small>有效缺陷密度</small>
          <b>{{ report.density_per_m }}<span class="unit">个/米</span></b>
          <div class="state-line"><span class="dim">报警阈值 {{ report.threshold_per_m }} 个/米</span></div>
        </div>
        <div class="kpi">
          <small>带钢长度</small>
          <b>{{ report.length_m }}<span class="unit">米</span></b>
        </div>
        <div class="kpi">
          <small>检测时长</small>
          <b>{{ report.duration_sec }}<span class="unit">秒</span></b>
        </div>
        <div class="kpi" :class="gradeKpiClass">
          <small>质量判级</small>
          <b :class="`grade-${(report.grade || 'a').toLowerCase()}`" style="font-size: 28px">{{ report.grade }}</b>
          <div class="state-line"><span>{{ report.advice }}</span></div>
        </div>
      </div>

      <div class="report-grid">
        <div class="panel">
          <div class="panel-hd">
            缺陷类别分布
            <span class="sub">按有效缺陷统计（已剔除误报）</span>
          </div>
          <div class="panel-bd">
            <div ref="pieEl" class="chart-box"></div>
          </div>
        </div>
        <div class="panel">
          <div class="panel-hd">
            复核状态构成
            <span class="sub">复核工作流进度</span>
          </div>
          <div class="panel-bd">
            <table class="grid-table">
              <tbody>
                <tr><td>待复核</td><td class="num">{{ report.pending }}</td></tr>
                <tr><td>已确认</td><td class="num">{{ report.confirmed }}</td></tr>
                <tr><td>误报</td><td class="num">{{ report.false_alarms }}</td></tr>
                <tr><td>有效合计</td><td class="num">{{ report.effective_total }}</td></tr>
              </tbody>
            </table>
            <div class="note">
              判级规则：有效缺陷密度 ≥ {{ report.threshold_per_m }} 个/米 判 C（阻断放行）；
              超过一半判 B；其余判 A（放行）。
            </div>
          </div>
        </div>
      </div>
    </template>
    <div v-else class="panel">
      <div class="panel-bd muted" style="padding: 24px; text-align: center">
        选择卷后查看报表 —— 通过「运行监控」开始一次检测即可生成卷记录
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { api } from '../api'

const coils = ref([])
const coilId = ref(null)
const report = ref(null)
const pieEl = ref(null)
const msg = ref('')
let chart = null

/* 工业图表主题（ISA-101：低饱和底、克制用色，类别色只用于区分不作装饰）。
   颜色从 CSS 变量读取，深浅主题切换时重绘（监听 sv-theme 事件）。 */
const INDUSTRIAL_PALETTE = ['#6b8fbc', '#8d9f6b', '#b08d5a', '#8a7fb0', '#5f9e9e', '#b07a7a', '#7a8a99', '#a39a6b']

function cssVar(name, fallback) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}

const gradeKpiClass = computed(() => {
  const g = (report.value?.grade || '').toUpperCase()
  return g === 'C' ? 'bad' : (g === 'B' ? 'warn' : 'ok')
})

async function loadCoils() {
  try {
    coils.value = await api('/api/coils')
    if (!coilId.value && coils.value.length) coilId.value = coils.value[0].id
    await loadReport()
  } catch (e) { msg.value = e.message }
}

async function loadReport() {
  if (!coilId.value) { report.value = null; return }
  try {
    report.value = await api(`/api/reports/coil/${coilId.value}`)
    await nextTick()
    render()
  } catch (e) { msg.value = e.message }
}

function render() {
  if (!pieEl.value || !report.value) return
  if (!chart) chart = echarts.init(pieEl.value, null, { renderer: 'canvas' })
  const counts = report.value.counts || {}
  const data = Object.entries(counts).map(([k, v]) => ({ name: k, value: v }))
  chart.setOption({
    backgroundColor: 'transparent',
    color: INDUSTRIAL_PALETTE,
    tooltip: {
      trigger: 'item',
      backgroundColor: cssVar('--bg-2', '#23272c'),
      borderColor: cssVar('--line-strong', '#4a515a'),
      borderWidth: 1,
      textStyle: { color: cssVar('--text', '#c9ced6'), fontSize: 13 },
    },
    legend: {
      right: 8, top: 'center', orient: 'vertical',
      textStyle: { color: cssVar('--text-dim', '#8a929c'), fontSize: 12 },
      itemWidth: 10, itemHeight: 10,
    },
    series: [{
      type: 'pie',
      radius: ['46%', '72%'],
      center: ['40%', '50%'],
      label: {
        color: cssVar('--text', '#c9ced6'), fontSize: 12,
        formatter: '{b} {c}',
      },
      labelLine: { lineStyle: { color: cssVar('--line-strong', '#4a515a') } },
      itemStyle: { borderColor: cssVar('--bg-1', '#1c1f23'), borderWidth: 2 },
      data: data.length ? data : [{ name: '无缺陷', value: 1 }],
    }],
  }, true)
}

function onResize() { chart && chart.resize() }
/* 深浅主题切换时重绘图表（颜色全部取自 CSS 变量） */
function onThemeChange() { render() }

watch(coilId, loadReport)
onMounted(() => {
  loadCoils()
  window.addEventListener('resize', onResize)
  window.addEventListener('sv-theme', onThemeChange)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  window.removeEventListener('sv-theme', onThemeChange)
  chart && chart.dispose()
  chart = null
})
</script>
