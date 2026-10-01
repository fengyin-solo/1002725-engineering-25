<template>
  <section class="page" data-module="safetycheck">
    <header class="page-head">
      <div>
        <h2>安全巡检管理</h2>
        <p class="page-desc">巡检要点按区域配置、整改期限按隐患等级自动计算；换现场只需修改配置，无需改动本页面。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记巡检记录</button>
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
        <span>巡检区域</span>
        <select v-model="filters.area">
          <option value="">全部区域</option>
          <option v-for="area in areas" :key="area.code" :value="area.name">{{ area.name }}</option>
        </select>
      </label>
      <label class="filter-item">
        <span>隐患等级</span>
        <select v-model="filters.risk_level">
          <option value="">全部等级</option>
          <option v-for="level in riskLevels" :key="level.code" :value="level.name">
            {{ level.name }}（{{ level.deadline_days }} 天）
          </option>
        </select>
      </label>
      <label class="filter-item">
        <span>巡检状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] || '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
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
          <td :colspan="columns.length + 1" class="empty-state">暂无安全巡检数据，可先登记巡检记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条安全巡检记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="creating" class="modal-mask" @click.self="creating = false">
      <form class="modal-card" @submit.prevent="submitCreate">
        <h3>登记巡检记录</h3>
        <p class="modal-tip">区域、要点、等级选项均来自后端配置；整改期限提交后按等级默认天数自动计算。</p>
        <label v-for="field in formFields" :key="field.key" class="filter-item modal-field">
          <span>{{ field.label }}</span>
          <input
            v-if="field.type === 'text' || field.type === 'date'"
            v-model="form[field.key]"
            :type="field.type"
          />
          <select v-else-if="field.type === 'area'" v-model="form.area" @change="onAreaChange">
            <option value="" disabled>请选择巡检区域</option>
            <option v-for="area in areas" :key="area.code" :value="area.name">{{ area.name }}</option>
          </select>
          <select v-else-if="field.type === 'point'" v-model="form.point">
            <option value="" disabled>请选择巡检要点</option>
            <option v-for="point in areaPoints" :key="point.code" :value="point.name">
              {{ point.name }}（{{ point.risk_level }}）
            </option>
          </select>
          <select v-else-if="field.type === 'level'" v-model="form.riskLevel">
            <option value="">无隐患</option>
            <option v-for="level in riskLevels" :key="level.code" :value="level.name">
              {{ level.name }}（{{ level.deadline_days }} 天）
            </option>
          </select>
        </label>
        <label class="filter-item modal-field">
          <span>发现隐患</span>
          <textarea v-model="form.found" rows="2" placeholder="无隐患可留空"></textarea>
        </label>
        <label class="filter-item modal-field">
          <span>整改措施</span>
          <textarea v-model="form.measure" rows="2" placeholder="整改要求与落实方式（可留空）"></textarea>
        </label>
        <div class="modal-actions">
          <button class="btn ghost" type="button" @click="creating = false">取消</button>
          <button class="btn primary" type="submit">提交登记</button>
        </div>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
type Checkpoint = { code: string; name: string; risk_level: string }
type Area = { code: string; name: string; checkpoints: Checkpoint[] }
type RiskLevel = { code: string; name: string; deadline_days: number }

const ENDPOINT = '/api/safetycheck'
const columns = ['巡检编号', '巡检区域', '巡检要点', '隐患等级', '巡检日期', '巡检人员', '发现隐患', '整改措施', '发现日期', '整改期限', '巡检状态']
const actions = ['开始巡检', '提交隐患', '确认闭合']
const statuses = ['待巡检', '巡检中', '待整改', '已闭合']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const areas = ref<Area[]>([])
const riskLevels = ref<RiskLevel[]>([])
const filters = ref<Record<string, string>>({ keyword: '', area: '', risk_level: '', status: '' })

const stats = computed(() => {
  const pending = rows.value.filter((row) => row.status === '待巡检').length
  const fixing = rows.value.filter((row) => row.status === '待整改').length
  const closed = rows.value.filter((row) => row.status === '已闭合').length
  return [
    { label: '待巡检区域', value: pending },
    { label: '待整改隐患', value: fixing },
    { label: '已闭合隐患', value: closed },
  ]
})

const creating = ref(false)
const form = ref<Record<string, string>>({
  id: '', area: '', point: '', date: '', inspector: '', riskLevel: '', found: '', measure: '',
})
const formFields = [
  { key: 'id', label: '巡检编号', type: 'text' },
  { key: 'area', label: '巡检区域', type: 'area' },
  { key: 'point', label: '巡检要点', type: 'point' },
  { key: 'date', label: '巡检日期', type: 'date' },
  { key: 'inspector', label: '巡检人员', type: 'text' },
  { key: 'riskLevel', label: '隐患等级', type: 'level' },
]
const areaPoints = computed(
  () => areas.value.find((area) => area.name === form.value.area)?.checkpoints ?? [],
)

function onAreaChange() {
  form.value.point = ''
}

function openCreate() {
  form.value = { id: '', area: '', point: '', date: '', inspector: '', riskLevel: '', found: '', measure: '' }
  errorMessage.value = ''
  creating.value = true
}

async function submitCreate() {
  errorMessage.value = ''
  const payload = {
    巡检编号: form.value.id,
    巡检区域: form.value.area,
    巡检要点: form.value.point,
    巡检日期: form.value.date,
    巡检人员: form.value.inspector,
    隐患等级: form.value.found ? form.value.riskLevel : '',
    发现隐患: form.value.found,
    整改措施: form.value.measure,
    发现日期: form.value.date,
  }
  try {
    const response = await request(ENDPOINT, { method: 'POST', body: JSON.stringify({ values: payload }) })
    const result = await response.json()
    if (!response.ok || !result.ok) {
      throw new Error(result.detail || result.message || '巡检记录登记失败')
    }
    creating.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '巡检记录登记失败'
  }
}

function resetFilters() {
  filters.value = { keyword: '', area: '', risk_level: '', status: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const result = await response.json()
    if (!response.ok || !result.ok) {
      throw new Error(result.message || '安全巡检动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '安全巡检操作失败'
  }
}

async function loadConfig() {
  try {
    const response = await request(`${ENDPOINT}/config`)
    if (!response.ok) {
      throw new Error('巡检配置读取失败')
    }
    const data = await response.json()
    areas.value = data.areas ?? []
    riskLevels.value = data.risk_levels ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '巡检配置读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(filters.value)) {
    if (value) {
      params.set(key, value)
    }
  }
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
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
  await loadConfig()
  await reload()
})
</script>
