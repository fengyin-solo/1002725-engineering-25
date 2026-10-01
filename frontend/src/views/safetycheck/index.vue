<template>
  <section class="page" data-module="safetycheck">
    <header class="page-head">
      <div>
        <h2>安全巡检管理</h2>
        <p class="page-desc">维护巡检记录，围绕巡检编号、巡检区域、巡检日期、巡检人员做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记巡检记录</button>
        <button class="btn" type="button" @click="reloadConfig">重载巡检配置</button>
        <button class="btn" type="button" @click="exportRows">导出安全巡检清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>巡检编号</span>
        <input v-model="filters.keyword" placeholder="按巡检编号检索" />
      </label>
      <label class="filter-item">
        <span>巡检状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>巡检区域</span>
        <select v-model="filters.area">
          <option value="">全部区域</option>
          <option v-for="area in config?.areas ?? []" :key="area.code" :value="area.code">{{ area.name }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>检查要点</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="point-cell">{{ row['检查要点'] || '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in availableActions(row)"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无安全巡检数据，可先登记巡检记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条安全巡检记录</span>
      <span v-if="configMeta" class="config-meta">配置版本 v{{ configMeta.version }} · {{ configMeta.config_hash.slice(0, 8) }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 登记巡检记录 -->
    <div v-if="modal === 'create'" class="modal-mask" @click.self="closeModal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记巡检记录</h3>
        <p class="modal-hint">巡检区域与检查要点来自巡检配置，换现场只需改配置，无需改代码。</p>
        <label class="form-item">
          <span>巡检编号 *</span>
          <input v-model="createForm.number" required placeholder="如 SAFE-20261001-01" />
        </label>
        <label class="form-item">
          <span>巡检区域 *</span>
          <select v-model="createForm.area" required>
            <option value="" disabled>请选择区域</option>
            <option v-for="area in config?.areas ?? []" :key="area.code" :value="area.code">{{ area.name }}</option>
          </select>
        </label>
        <label class="form-item">
          <span>巡检日期 *</span>
          <input v-model="createForm.date" type="date" required />
        </label>
        <label class="form-item">
          <span>巡检人员</span>
          <input v-model="createForm.person" />
        </label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="closeModal">取消</button>
          <button class="btn primary" type="submit">登记</button>
        </div>
      </form>
    </div>

    <!-- 提交隐患：勾选该区域要点、选等级，自动带出默认整改期限 -->
    <div v-if="modal === 'hazard'" class="modal-mask" @click.self="closeModal">
      <form class="modal" @submit.prevent="submitHazard">
        <h3>提交隐患 · {{ hazardTarget?.['巡检编号'] }}</h3>
        <p class="modal-hint">
          区域：{{ areaName(hazardTarget?.['_area_code']) }}；整改期限默认按「巡检日期 + 隐患等级天数」计算，可手工调整。
        </p>
        <fieldset class="form-item">
          <legend>检查要点 *（仅显示该区域配置的要点，可多选）</legend>
          <label v-for="point in pointsForArea(hazardTarget?.['_area_code'])" :key="point.code" class="check-line">
            <input type="checkbox" :value="point.code" v-model="hazardForm.points" />
            <span>{{ point.text }}</span>
          </label>
          <p v-if="!pointsForArea(hazardTarget?.['_area_code']).length" class="error-text">该区域未配置检查要点，请先补配置。</p>
        </fieldset>
        <label class="form-item">
          <span>隐患等级 *</span>
          <select v-model="hazardForm.level" required @change="syncDeadline">
            <option value="" disabled>请选择等级</option>
            <option v-for="level in config?.hazard_levels ?? []" :key="level.code" :value="level.code">
              {{ level.name }}（默认 {{ level.default_deadline_days }} 天）
            </option>
          </select>
        </label>
        <label class="form-item">
          <span>发现隐患</span>
          <textarea v-model="hazardForm.hazard" rows="2"></textarea>
        </label>
        <label class="form-item">
          <span>整改措施</span>
          <textarea v-model="hazardForm.action" rows="2"></textarea>
        </label>
        <label class="form-item">
          <span>整改期限</span>
          <input v-model="hazardForm.deadline" type="date" />
        </label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="closeModal">取消</button>
          <button class="btn primary" type="submit">提交隐患</button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import { request } from '@/api/client'

type Scalar = string | number | null
type Row = Record<string, Scalar>

type HazardLevel = { code: string; name: string; default_deadline_days: number }
type Area = { code: string; name: string }
type Checkpoint = { code: string; text: string; risk_level: string }
type CheckpointGroup = { area: string; area_name: string; items: Checkpoint[] }
type SafetyConfig = {
  version: number
  config_hash: string
  hazard_levels: HazardLevel[]
  areas: Area[]
  checkpoint_groups: CheckpointGroup[]
}

const ENDPOINT = '/api/safetycheck'
const columns = ["巡检编号", "巡检区域", "巡检日期", "巡检人员", "发现隐患", "整改措施", "整改期限", "巡检状态"]
const statuses = ["待巡检", "巡检中", "待整改", "已闭合"]
const stats = [{"label": "待巡检区域", "value": 0}, {"label": "待整改隐患", "value": 0}, {"label": "已闭合隐患", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const config = ref<SafetyConfig | null>(null)
const configMeta = ref<{ version: number; config_hash: string } | null>(null)
const filters = reactive<{ keyword: string; status: string; area: string }>({ keyword: '', status: '', area: '' })
const modal = ref<'' | 'create' | 'hazard'>('')

const createForm = reactive({ number: '', area: '', date: '', person: '' })
const hazardTarget = ref<Row | null>(null)
const hazardForm = reactive<{ points: string[]; level: string; hazard: string; action: string; deadline: string }>({
  points: [],
  level: '',
  hazard: '',
  action: '',
  deadline: '',
})

function availableActions(row: Row): string[] {
  switch (row.status) {
    case '待巡检':
      return ['开始巡检']
    case '巡检中':
      return ['提交隐患', '确认闭合']
    case '待整改':
      return ['确认闭合']
    default:
      return []
  }
}

function areaName(code?: string | number | null): string {
  return config.value?.areas.find((area) => area.code === code)?.name ?? String(code ?? '')
}

function pointsForArea(code?: string | number | null): Checkpoint[] {
  return config.value?.checkpoint_groups.find((group) => group.area === code)?.items ?? []
}

function addDays(isoDate: string, days: number): string {
  const base = new Date(`${isoDate}T00:00:00`)
  base.setDate(base.getDate() + days)
  return base.toISOString().slice(0, 10)
}

function resetFilters() {
  filters.keyword = ''
  filters.status = ''
  filters.area = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  Object.assign(createForm, { number: '', area: '', date: '', person: '' })
  modal.value = 'create'
}

function closeModal() {
  modal.value = ''
  hazardTarget.value = null
}

function runAction(action: string, row: Row) {
  if (action === '提交隐患') {
    hazardTarget.value = row
    Object.assign(hazardForm, { points: [], level: '', hazard: '', action: '', deadline: '' })
    modal.value = 'hazard'
    return
  }
  errorMessage.value = ''
  void postAction(row.id as number, { action })
}

function syncDeadline() {
  const level = config.value?.hazard_levels.find((item) => item.code === hazardForm.level)
  const dateValue = hazardTarget.value ? String(hazardTarget.value['巡检日期'] ?? '') : ''
  if (level && dateValue) {
    hazardForm.deadline = addDays(dateValue, level.default_deadline_days)
  }
}

async function submitCreate() {
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({
        values: {
          巡检编号: createForm.number,
          巡检区域: createForm.area,
          巡检日期: createForm.date,
          巡检人员: createForm.person,
        },
      }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? '巡检记录登记失败')
    }
    closeModal()
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '巡检记录登记失败'
  }
}

async function submitHazard() {
  if (!hazardTarget.value) return
  if (!hazardForm.points.length || !hazardForm.level) {
    errorMessage.value = '请至少勾选一个检查要点并选择隐患等级'
    return
  }
  try {
    const response = await request(`${ENDPOINT}/${hazardTarget.value.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({
        values: {
          action: '提交隐患',
          检查要点: hazardForm.points,
          隐患等级: hazardForm.level,
          发现隐患: hazardForm.hazard,
          整改措施: hazardForm.action,
          整改期限: hazardForm.deadline || undefined,
        },
      }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? '隐患提交失败')
    }
    closeModal()
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '隐患提交失败'
  }
}

async function postAction(id: number, values: Record<string, unknown>) {
  try {
    const response = await request(`${ENDPOINT}/${id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message ?? '安全巡检动作未生效')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '安全巡检操作失败'
  }
}

async function loadConfig() {
  const response = await request(`${ENDPOINT}/config`)
  if (!response.ok) {
    throw new Error('巡检配置读取失败')
  }
  const payload = (await response.json()) as SafetyConfig
  config.value = payload
  configMeta.value = { version: payload.version, config_hash: payload.config_hash }
}

async function reloadConfig() {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/config/reload`, { method: 'POST' })
    const payload = await response.json()
    if (!response.ok) {
      throw new Error(payload.detail ?? '配置重载失败')
    }
    await loadConfig()
    await reload()
    errorMessage.value = payload.changed
      ? '配置已更新（既有巡检记录保持不变）'
      : '配置未变化，重复导入已跳过'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '配置重载失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.keyword) query.set('keyword', filters.keyword)
  if (filters.status) query.set('status', filters.status)
  if (filters.area) query.set('area', filters.area)
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
    if (!response.ok) {
      throw new Error('巡检记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '安全巡检列表读取失败'
  }
}

onMounted(async () => {
  try {
    await loadConfig()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '巡检配置读取失败'
  }
  await reload()
})
</script>

<style scoped>
.config-meta { color: var(--muted); }
.point-cell { max-width: 260px; }
.modal-mask {
  position: fixed; inset: 0; background: rgba(15, 23, 42, 0.45);
  display: flex; align-items: flex-start; justify-content: center; padding: 48px 16px; z-index: 50;
}
.modal {
  background: #fff; border-radius: 10px; padding: 18px 20px; width: 520px; max-width: 100%;
  max-height: 86vh; overflow: auto; box-shadow: 0 18px 48px rgba(15, 23, 42, 0.25);
}
.modal h3 { margin: 0 0 4px; font-size: 16px; }
.modal-hint { margin: 0 0 12px; color: var(--muted); font-size: 12px; }
.form-item { display: flex; flex-direction: column; gap: 4px; margin-bottom: 10px; border: none; padding: 0; margin-inline: 0; }
.form-item > span, .form-item legend { font-size: 12px; color: var(--muted); }
.form-item input, .form-item select, .form-item textarea {
  border: 1px solid var(--border); border-radius: 6px; padding: 6px 8px; font: inherit; width: 100%;
}
.check-line { display: flex; gap: 6px; align-items: flex-start; font-size: 13px; margin: 2px 0; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 6px; }
</style>
