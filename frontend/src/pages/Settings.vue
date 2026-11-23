<template>
  <div>
    <div class="panel">
      <div class="panel-hd">
        操作员会话
        <span class="sub">写操作（开始/结束检测、复核、报警确认、修改设置）需登录</span>
      </div>
      <div class="panel-bd">
        <div class="form-grid" style="grid-template-columns: 200px 200px auto">
          <div class="form-row">
            <label>用户名</label>
            <input v-model="usr" class="input" placeholder="admin / operator / viewer" />
          </div>
          <div class="form-row">
            <label>密码</label>
            <input v-model="pwd" class="input" type="password" @keyup.enter="login" />
          </div>
          <div class="form-row">
            <label>&nbsp;</label>
            <div style="display: flex; gap: 8px; align-items: center">
              <button class="btn primary" @click="login">登录</button>
              <span :class="['tag', who ? 'confirmed' : 'idle']">{{ who || '未登录' }}</span>
            </div>
          </div>
        </div>
        <div class="note">
          初始账号：admin/admin123（管理员）· operator/operator123（操作员）· viewer/viewer123（只读）。
          生产部署后请在服务端修改默认口令。
        </div>
      </div>
    </div>

    <template v-if="cfg">
      <div class="panel">
        <div class="panel-hd">
          模型热切换
          <span class="sub">甲方样本上线无需重启系统</span>
        </div>
        <div class="panel-bd">
          <div class="form-grid" style="grid-template-columns: 1fr 180px">
            <div class="form-row">
              <label>模型权重路径（.pt / .onnx / .engine）</label>
              <input v-model="cfg.model_path" class="input mono" />
            </div>
            <div class="form-row">
              <label>&nbsp;</label>
              <button class="btn primary" @click="reloadModel">应用热切换</button>
            </div>
          </div>
          <div class="form-row" style="margin-top: 8px">
            <label>类别名称（逗号分隔，顺序与模型输出一致）</label>
            <input v-model="classNamesText" class="input" />
          </div>
          <div class="note" v-if="modelInfo">
            当前推理后端：{{ modelInfo.backend || '未初始化' }} / {{ modelInfo.provider || '—' }}
            ｜ 可用 provider：{{ (modelInfo.available_providers || []).join(', ') || '—' }}
            <br />热切换在下一次「开始检测」生效；检测运行中需先结束本卷（接口返回 409）。
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="panel-hd">
          推理后端与大图切片
          <span class="sub">auto 模式按 TensorRT → CUDA → CPU 自动降级</span>
        </div>
        <div class="panel-bd">
          <div class="form-grid">
            <div class="form-row">
              <label>推理后端</label>
              <select v-model="cfg.infer_providers" class="input">
                <option value="auto">auto（自动降级）</option>
                <option value="tensorrt">tensorrt（TensorRT EP）</option>
                <option value="cuda">cuda（CUDA EP）</option>
                <option value="cpu">cpu（纯 CPU）</option>
              </select>
            </div>
            <div class="form-row inline">
              <label class="check-line" style="margin-top: 14px">
                <input v-model="cfg.fp16" type="checkbox" />
                FP16（仅 GPU / TensorRT-EP 生效）
              </label>
            </div>
            <div class="form-row inline">
              <label class="check-line" style="margin-top: 14px">
                <input v-model="cfg.tiling.enabled" type="checkbox" />
                启用大图切片
              </label>
            </div>
            <div class="form-row">
              <label>切片尺寸</label>
              <select v-model.number="cfg.tiling.tile_size" class="input">
                <option :value="512">512 × 512</option>
                <option :value="1024">1024 × 1024</option>
                <option :value="2048">2048 × 2048</option>
              </select>
            </div>
            <div class="form-row">
              <label>重叠比例（0.05 ~ 0.5）</label>
              <input v-model.number="cfg.tiling.overlap" class="input mono" type="number" step="0.05" min="0.05" max="0.5" />
            </div>
            <div class="form-row">
              <label>切片触发边长（像素）</label>
              <input v-model.number="cfg.tiling.trigger_min_side" class="input mono" type="number" step="100" min="320" />
            </div>
          </div>
          <div class="note">
            切片口径对齐工业线阵检测惯例：大图按 512/1024/2048 切块、5%~50% 重叠、合并后统一类感知 NMS；
            输入小于触发边长时整图推理，零额外开销。
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="panel-hd">检测与报警参数</div>
        <div class="panel-bd">
          <div class="form-grid">
            <div class="form-row">
              <label>conf 阈值</label>
              <input v-model.number="cfg.conf" class="input mono" type="number" step="0.01" min="0" max="1" />
            </div>
            <div class="form-row">
              <label>iou 阈值</label>
              <input v-model.number="cfg.iou" class="input mono" type="number" step="0.01" min="0" max="1" />
            </div>
            <div class="form-row">
              <label>帧率 fps</label>
              <input v-model.number="cfg.fps" class="input mono" type="number" step="1" min="1" max="30" />
            </div>
            <div class="form-row">
              <label>证据帧保存阈值</label>
              <input v-model.number="cfg.evidence_conf" class="input mono" type="number" step="0.05" min="0" max="1" />
            </div>
            <div class="form-row">
              <label>单卷缺陷数报警阈值</label>
              <input v-model.number="cfg.alarms.min_defects_per_coil" class="input mono" type="number" step="1" min="1" />
            </div>
            <div class="form-row">
              <label>密度报警阈值（个/米）</label>
              <input v-model.number="cfg.alarms.density_per_m" class="input mono" type="number" step="0.1" min="0" />
            </div>
            <div class="form-row">
              <label>每帧长度标定（米）</label>
              <input v-model.number="cfg.meters_per_frame" class="input mono" type="number" step="0.01" min="0" />
            </div>
            <div class="form-row">
              <label>证据帧保留天数</label>
              <input v-model.number="retentionDays" class="input mono" type="number" step="1" min="1" />
            </div>
          </div>
          <div class="form-row" style="margin-top: 8px">
            <label>优先报警类别（逗号分隔）</label>
            <input v-model="priority" class="input" />
          </div>
          <div class="form-row" style="margin-top: 8px">
            <label>默认数据源（视频文件或图像目录；留空且未启用相机 = 合成帧）</label>
            <input v-model="cfg.source_path" class="input mono" />
          </div>
          <label class="check-line" style="margin-top: 10px">
            <input v-model="cfg.auth_enabled" type="checkbox" />
            启用登录鉴权（关闭后全部写操作按管理员放行，仅限内网调试）
          </label>
        </div>
      </div>

      <div class="panel">
        <div class="panel-hd">
          相机（SDK 适配层）
          <span class="sub">接入步骤见 docs/camera_integration.md</span>
        </div>
        <div class="panel-bd">
          <div class="form-grid">
            <div class="form-row inline">
              <label class="check-line" style="margin-top: 14px">
                <input v-model="cfg.camera.enabled" type="checkbox" />
                启用相机数据源
              </label>
            </div>
            <div class="form-row">
              <label>适配器</label>
              <select v-model="cfg.camera.adapter" class="input">
                <option v-for="a in (modelInfo?.camera_adapters || ['opencv'])" :key="a" :value="a">{{ a }}</option>
              </select>
            </div>
            <div class="form-row">
              <label>index（opencv）</label>
              <input v-model.number="cfg.camera.index" class="input mono" type="number" step="1" min="0" />
            </div>
            <div class="form-row">
              <label>serial（hikrobot / pypylon 序列号优先匹配）</label>
              <input v-model="cfg.camera.serial" class="input mono" />
            </div>
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="panel-hd">
          报警外联动（PLC）
          <span class="sub">报警置位 → 脉冲 → 自动复位；写失败不阻塞检测</span>
        </div>
        <div class="panel-bd">
          <div class="form-grid">
            <div class="form-row inline">
              <label class="check-line" style="margin-top: 14px">
                <input v-model="cfg.linkage.enabled" type="checkbox" />
                启用联动
              </label>
            </div>
            <div class="form-row">
              <label>驱动</label>
              <select v-model="cfg.linkage.driver" class="input">
                <option value="dryrun">dryrun（仅日志，联调先行）</option>
                <option value="snap7">snap7（西门子 S7）</option>
                <option value="modbus">modbus（Modbus TCP）</option>
              </select>
            </div>
            <div class="form-row">
              <label>PLC 地址</label>
              <input v-model="cfg.linkage.host" class="input mono" />
            </div>
            <div class="form-row">
              <label>脉冲宽度 ms</label>
              <input v-model.number="cfg.linkage.pulse_ms" class="input mono" type="number" step="100" min="100" />
            </div>
          </div>
          <div v-if="cfg.linkage.driver === 'snap7'" class="form-grid" style="margin-top: 8px">
            <div class="form-row">
              <label>rack</label>
              <input v-model.number="cfg.linkage.rack" class="input mono" type="number" step="1" min="0" />
            </div>
            <div class="form-row">
              <label>slot</label>
              <input v-model.number="cfg.linkage.slot" class="input mono" type="number" step="1" min="0" />
            </div>
            <div class="form-row">
              <label>DB 号</label>
              <input v-model.number="cfg.linkage.db" class="input mono" type="number" step="1" min="1" />
            </div>
            <div class="form-row">
              <label>字节地址（DB1.DBX8080.0 填 8080）</label>
              <input v-model.number="cfg.linkage.byte" class="input mono" type="number" step="1" min="0" />
            </div>
            <div class="form-row">
              <label>位（0~7）</label>
              <input v-model.number="cfg.linkage.bit" class="input mono" type="number" step="1" min="0" max="7" />
            </div>
          </div>
          <div v-if="cfg.linkage.driver === 'modbus'" class="form-grid" style="margin-top: 8px">
            <div class="form-row">
              <label>端口</label>
              <input v-model.number="cfg.linkage.modbus_port" class="input mono" type="number" step="1" />
            </div>
            <div class="form-row">
              <label>线圈地址</label>
              <input v-model.number="cfg.linkage.modbus_coil" class="input mono" type="number" step="1" min="0" />
            </div>
          </div>
          <div style="display: flex; gap: 8px; align-items: center; margin-top: 10px">
            <button class="btn" @click="testLinkage">测试联动（点动脉冲）</button>
            <span v-if="linkageMsg" :class="['msg-line', linkageOk ? 'ok' : '']">{{ linkageMsg }}</span>
          </div>
          <div class="note">
            正式联调顺序：dryrun 验证软件侧时序 → 现场改 snap7/modbus 并核对位地址 →
            点「测试联动」用万用表/PLC 监视表确认置位复位。断线自动重连，联动失败仅记日志。
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="panel-bd" style="display: flex; gap: 10px; align-items: center">
          <button class="btn primary" @click="save">保存全部配置</button>
          <span v-if="msg" :class="['msg-line', msgOk ? 'ok' : '']">{{ msg }}</span>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'

const cfg = ref(null)
const modelInfo = ref(null)
const priority = ref('')
const classNamesText = ref('')
const retentionDays = ref(30)
const usr = ref('')
const pwd = ref('')
const who = ref(localStorage.getItem('sv_user') || '')
const msg = ref('')
const msgOk = ref(false)
const linkageMsg = ref('')
const linkageOk = ref(false)

async function loadCfg() {
  try {
    cfg.value = await api('/api/settings')
    priority.value = (cfg.value.alarms?.priority_classes || []).join(', ')
    classNamesText.value = (cfg.value.class_names || []).join(', ')
    retentionDays.value = cfg.value.retention?.evidence_days || 30
    modelInfo.value = await api('/api/model/info')
  } catch (e) { msg.value = e.message }
}

async function login() {
  msg.value = ''
  try {
    const r = await api('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username: usr.value, password: pwd.value }),
    })
    localStorage.setItem('sv_token', r.token)
    who.value = `${r.user.username}（${r.user.role}）`
    localStorage.setItem('sv_user', who.value)
    msg.value = '登录成功'
    msgOk.value = true
  } catch (e) { msg.value = e.message; msgOk.value = false }
}

async function reloadModel() {
  msg.value = ''
  try {
    const r = await api('/api/model/reload', {
      method: 'POST',
      body: JSON.stringify({
        model_path: cfg.value.model_path,
        class_names: classNamesText.value.split(',').map(s => s.trim()).filter(Boolean),
      }),
    })
    msg.value = `模型已切换（${r.note}）`
    msgOk.value = true
    modelInfo.value = await api('/api/model/info')
  } catch (e) { msg.value = e.message; msgOk.value = false }
}

async function testLinkage() {
  linkageMsg.value = ''
  try {
    const r = await api('/api/linkage/test', { method: 'POST' })
    linkageOk.value = !!r.ok
    linkageMsg.value = r.ok
      ? `联动成功（${r.driver}）`
      : `联动失败：${r.error || r.driver}`
  } catch (e) { linkageMsg.value = e.message; linkageOk.value = false }
}

async function save() {
  msg.value = ''
  const alarms = {
    ...(cfg.value.alarms || {}),
    priority_classes: priority.value.split(',').map(s => s.trim()).filter(Boolean),
  }
  try {
    await api('/api/settings', {
      method: 'PUT',
      body: JSON.stringify({
        ...cfg.value,
        alarms,
        retention: { evidence_days: retentionDays.value },
      }),
    })
    msg.value = '配置已保存（模型/数据源/相机在下次「开始检测」生效；阈值/联动实时生效）'
    msgOk.value = true
    modelInfo.value = await api('/api/model/info')
  } catch (e) { msg.value = e.message; msgOk.value = false }
}

onMounted(loadCfg)
</script>
