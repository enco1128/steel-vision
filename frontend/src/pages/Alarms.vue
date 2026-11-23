<template>
  <div>
    <div class="toolbar">
      <span class="field-label">级别</span>
      <select v-model="levelFilter" class="input" style="width: 110px">
        <option value="">全部</option>
        <option value="critical">临界</option>
        <option value="warn">警告</option>
        <option value="info">提示</option>
      </select>
      <label class="check-line">
        <input v-model="onlyUnacked" type="checkbox" />
        只看未确认
      </label>
      <button class="btn" @click="load">刷新</button>
      <span class="spacer"></span>
      <span class="muted">
        未确认：临界 {{ unackedBy.critical }} · 警告 {{ unackedBy.warn }} · 提示 {{ unackedBy.info }}
      </span>
      <span v-if="msg" class="msg-line">{{ msg }}</span>
    </div>

    <div class="panel">
      <div class="panel-hd">
        报警记录
        <span class="sub">ISA-18.2 报警生命周期 · 确认(ack)需登录操作员权限</span>
      </div>
      <div class="panel-bd flush">
        <table class="grid-table">
          <thead>
            <tr>
              <th style="width: 56px">ID</th>
              <th style="width: 150px">时间</th>
              <th style="width: 76px">级别</th>
              <th style="width: 150px">规则</th>
              <th>报警内容</th>
              <th style="width: 200px">确认状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in filtered" :key="a.id">
              <td class="num">{{ a.id }}</td>
              <td class="mono" style="font-size: 12px">{{ a.ts }}</td>
              <td><span :class="['tag', a.level]">{{ levelLabel[a.level] || a.level }}</span></td>
              <td class="mono" style="font-size: 12px">{{ a.rule }}</td>
              <td>{{ a.message }}</td>
              <td>
                <span v-if="a.acked" class="tag confirmed">已确认 · {{ a.acked_by || '—' }}</span>
                <button v-else class="btn tiny" @click="ack(a)">确认报警</button>
              </td>
            </tr>
            <tr v-if="!filtered.length">
              <td colspan="6" class="muted" style="text-align: center; padding: 18px">
                {{ alarms.length ? '当前筛选条件下无记录' : '暂无报警记录' }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'

const alarms = ref([])
const msg = ref('')
const levelFilter = ref('')
const onlyUnacked = ref(false)
const levelLabel = { info: '提示', warn: '警告', critical: '临界' }

const filtered = computed(() => {
  let rows = alarms.value
  if (levelFilter.value) rows = rows.filter(a => a.level === levelFilter.value)
  if (onlyUnacked.value) rows = rows.filter(a => !a.acked)
  return rows
})

const unackedBy = computed(() => {
  const c = { critical: 0, warn: 0, info: 0 }
  for (const a of alarms.value) if (!a.acked && c[a.level] !== undefined) c[a.level] += 1
  return c
})

async function load() {
  msg.value = ''
  try { alarms.value = await api('/api/alarms') }
  catch (e) { msg.value = e.message }
}

async function ack(a) {
  msg.value = ''
  try {
    await api(`/api/alarms/${a.id}/ack`, { method: 'POST' })
    await load()
  } catch (e) { msg.value = e.message }
}

onMounted(load)
</script>
