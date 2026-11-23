<template>
  <div>
    <div class="toolbar">
      <span class="field-label">卷</span>
      <select v-model="coilId" class="input" style="max-width: 340px" @change="loadDefects">
        <option v-if="!coils.length" :value="null">暂无卷记录</option>
        <option v-for="c in coils" :key="c.id" :value="c.id">
          {{ c.coil_no }} · {{ statusLabel[c.status] || c.status }} · 缺陷 {{ c.defect_count }}
        </option>
      </select>
      <span class="field-label">复核状态</span>
      <select v-model="filter" class="input" style="width: 110px">
        <option value="">全部</option>
        <option value="pending">待复核</option>
        <option value="confirmed">已确认</option>
        <option value="false_alarm">误报</option>
      </select>
      <button class="btn" @click="loadCoils">刷新</button>
      <span class="spacer"></span>
      <span class="muted">共 {{ filtered.length }} 条 · 待复核 {{ pendingCount }}</span>
      <span v-if="msg" class="msg-line">{{ msg }}</span>
    </div>

    <div class="panel">
      <div class="panel-hd">
        缺陷记录
        <span class="sub">按卷归档 · 证据帧可追溯</span>
      </div>
      <div class="panel-bd flush">
        <table class="grid-table">
          <thead>
            <tr>
              <th style="width: 56px">ID</th>
              <th style="width: 150px">时间</th>
              <th style="width: 130px">类别</th>
              <th style="width: 78px">置信度</th>
              <th>复核状态</th>
              <th>备注</th>
              <th style="width: 220px">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="d in filtered" :key="d.id">
              <td class="num">{{ d.id }}</td>
              <td class="mono" style="font-size: 12px">{{ d.ts }}</td>
              <td>{{ d.cls_name }}</td>
              <td class="num">{{ d.conf.toFixed(3) }}</td>
              <td><span :class="['tag', d.review_status]">{{ tagLabel[d.review_status] || d.review_status }}</span></td>
              <td class="muted">{{ d.review_note }}</td>
              <td>
                <button class="btn tiny" @click="view(d)">证据帧</button>
                <button class="btn tiny ok" @click="review(d, 'confirmed')">确认</button>
                <button class="btn tiny bad" @click="review(d, 'false_alarm')">误报</button>
              </td>
            </tr>
            <tr v-if="!filtered.length">
              <td colspan="7" class="muted" style="text-align: center; padding: 18px">
                {{ coils.length ? '当前筛选条件下无记录' : '暂无卷记录 —— 先在「运行监控」开始一次检测' }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="detail" class="modal" @click.self="detail = null">
      <div class="modal-box">
        <div class="modal-hd">
          <span>缺陷 #{{ detail.id }} · {{ detail.cls_name }} · conf {{ detail.conf.toFixed(3) }}</span>
          <button class="btn tiny" @click="detail = null">关闭</button>
        </div>
        <div class="modal-bd">
          <img v-if="evidenceSrc" class="evidence" :src="evidenceSrc" alt="证据帧" />
          <p v-else class="muted">该缺陷置信度低于证据阈值，未保存证据帧（检测事件已入库）</p>
          <input v-model="detail.review_note" class="input" placeholder="复核备注（可选）" />
        </div>
        <div class="modal-ft">
          <button class="btn bad" @click="review(detail, 'false_alarm'); detail = null">标记误报</button>
          <button class="btn ok" @click="review(detail, 'confirmed'); detail = null">确认缺陷</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import { evidenceUrl } from '../demo'

const coils = ref([])
const coilId = ref(null)
const defects = ref([])
const detail = ref(null)
const filter = ref('')
const msg = ref('')

const evidenceSrc = computed(() =>
  detail.value ? evidenceUrl(detail.value) : '')

const tagLabel = { pending: '待复核', confirmed: '已确认', false_alarm: '误报' }
const statusLabel = { running: '检测中', closed: '已结束' }

const filtered = computed(() =>
  filter.value ? defects.value.filter(d => d.review_status === filter.value) : defects.value)
const pendingCount = computed(() =>
  defects.value.filter(d => d.review_status === 'pending').length)

async function loadCoils() {
  try {
    coils.value = await api('/api/coils')
    if (!coilId.value && coils.value.length) coilId.value = coils.value[0].id
    await loadDefects()
  } catch (e) { msg.value = e.message }
}

async function loadDefects() {
  if (!coilId.value) { defects.value = []; return }
  try { defects.value = await api(`/api/coils/${coilId.value}/defects`) }
  catch (e) { msg.value = e.message }
}

async function review(d, status) {
  msg.value = ''
  try {
    await api(`/api/defects/${d.id}/review`, {
      method: 'POST',
      body: JSON.stringify({ status, note: d.review_note || '' }),
    })
    await loadDefects()
  } catch (e) { msg.value = e.message }
}

function view(d) { detail.value = { ...d } }

onMounted(loadCoils)
</script>
