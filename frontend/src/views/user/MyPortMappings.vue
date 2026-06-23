<template>
  <div>
    <el-card shadow="never" class="page-card filter-card">
      <el-tabs v-model="activeTab" @tab-change="handleTabChange">
        <el-tab-pane :label="`运行中 (${runningCount})`" name="running" />
        <el-tab-pane :label="`历史记录 (${historyCount})`" name="history" />
      </el-tabs>
      <el-form :inline="true" :model="filters" class="filter-form">
        <el-form-item label="关键词">
          <el-input
            v-model="filters.keyword"
            placeholder="客户端 / 目标 / 公网端口"
            clearable
            style="width: 220px"
            @keyup.enter="loadData"
          />
        </el-form-item>
        <el-form-item v-if="activeTab === 'history'" label="状态">
          <el-select v-model="filters.status" placeholder="全部" clearable style="width: 130px">
            <el-option label="已释放" value="deleted" />
            <el-option label="已过期" value="expired" />
            <el-option label="失败" value="failed" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="loadData">查询</el-button>
          <el-button @click="handleReset">重置</el-button>
          <el-button :icon="Refresh" @click="loadData">刷新</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-table v-loading="loading" :data="mappings" stripe border>
      <el-table-column prop="device_name" label="客户端" min-width="130" show-overflow-tooltip />
      <el-table-column label="目标地址" min-width="140">
        <template #default="{ row }">{{ row.target_host }}:{{ row.target_port }}</template>
      </el-table-column>
      <el-table-column label="公网映射" min-width="150">
        <template #default="{ row }">{{ row.public_host }}:{{ row.public_port }}</template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" effect="plain">{{ row.status_label || statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column v-if="activeTab === 'running'" label="剩余时间" width="130">
        <template #default="{ row }">{{ row.remaining_label || remainText(row.expire_at) }}</template>
      </el-table-column>
      <el-table-column v-if="activeTab === 'running'" label="到期时间" min-width="165">
        <template #default="{ row }">{{ row.expire_at_display || '永久' }}</template>
      </el-table-column>
      <el-table-column v-if="activeTab === 'history'" label="结束时间" min-width="165">
        <template #default="{ row }">{{ row.ended_at_display || '-' }}</template>
      </el-table-column>
      <el-table-column v-if="activeTab === 'history'" label="结束原因" width="120">
        <template #default="{ row }">{{ row.release_reason_label || '-' }}</template>
      </el-table-column>
      <el-table-column label="创建时间" min-width="165">
        <template #default="{ row }">{{ row.created_at_display || formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="连接命令" min-width="240">
        <template #default="{ row }">
          <template v-if="row.status === 'running' && row.connect_text">
            <span class="connect-text">{{ row.connect_text }}</span>
            <el-button link type="primary" @click="copyText(row.connect_text)">复制</el-button>
          </template>
          <span v-else class="muted">-</span>
        </template>
      </el-table-column>
      <el-table-column v-if="activeTab === 'running'" label="操作" width="80" fixed="right">
        <template #default="{ row }">
          <el-button link type="danger" @click="handleRelease(row)">释放</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && !mappings.length" :description="emptyText" />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getMyPortMappings, releasePortMapping } from '../../api'

const loading = ref(false)
const mappings = ref([])
const allRunning = ref([])
const allHistory = ref([])
const nowTick = ref(Date.now())
const activeTab = ref('running')
const filters = reactive({ keyword: '', status: '' })
let countdownTimer = null

const runningCount = computed(() => allRunning.value.length)
const historyCount = computed(() => allHistory.value.length)
const emptyText = computed(() =>
  activeTab.value === 'running' ? '暂无运行中的端口映射' : '暂无历史记录'
)

function statusType(status) {
  if (status === 'running') return 'success'
  if (status === 'expired') return 'warning'
  if (status === 'failed') return 'danger'
  return 'info'
}

function statusLabel(status) {
  const map = {
    running: '运行中',
    expired: '已过期',
    deleted: '已释放',
    released: '已释放',
    failed: '失败'
  }
  return map[status] || status
}

function formatTime(value) {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return value
  }
}

function remainText(expireAt) {
  if (!expireAt) return '永久'
  const diff = new Date(expireAt).getTime() - nowTick.value
  if (diff <= 0) return '已过期'
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `${mins} 分钟`
  const hours = Math.floor(mins / 60)
  return `${hours} 小时 ${mins % 60} 分`
}

function buildParams() {
  const params = { history: activeTab.value === 'history' }
  if (filters.keyword.trim()) params.keyword = filters.keyword.trim()
  if (activeTab.value === 'history' && filters.status) params.status = filters.status
  return params
}

async function loadCounts() {
  const [running, history] = await Promise.all([
    getMyPortMappings({ history: false }),
    getMyPortMappings({ history: true })
  ])
  allRunning.value = running
  allHistory.value = history
}

async function loadData() {
  loading.value = true
  try {
    mappings.value = await getMyPortMappings(buildParams())
    if (activeTab.value === 'running') allRunning.value = mappings.value
    else allHistory.value = mappings.value
  } finally {
    loading.value = false
  }
}

async function refreshAll() {
  await Promise.all([loadData(), loadCounts()])
}

function handleTabChange() {
  filters.status = ''
  loadData()
}

function handleReset() {
  filters.keyword = ''
  filters.status = ''
  loadData()
}

async function handleRelease(row) {
  await ElMessageBox.confirm('确定释放该端口映射？释放后将移入历史记录。', '确认')
  await releasePortMapping(row.id)
  ElMessage.success('已释放')
  refreshAll()
}

async function copyText(text) {
  await navigator.clipboard.writeText(text)
  ElMessage.success('已复制')
}

onMounted(async () => {
  await refreshAll()
  countdownTimer = setInterval(() => {
    nowTick.value = Date.now()
  }, 1000)
})

onUnmounted(() => {
  if (countdownTimer) clearInterval(countdownTimer)
})
</script>

<style scoped>
.filter-card {
  margin-bottom: 12px;
}

.filter-form {
  margin-top: 8px;
}

.connect-text {
  word-break: break-all;
  margin-right: 8px;
}

.muted {
  color: #909399;
}
</style>
