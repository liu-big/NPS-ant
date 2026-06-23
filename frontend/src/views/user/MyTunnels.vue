<template>
  <div>
    <el-card shadow="never" class="page-card filter-card">
      <el-form :inline="true" :model="filters" class="filter-form">
        <el-form-item label="关键词">
          <el-input
            v-model="filters.keyword"
            placeholder="设备名 / 备注 / 端口"
            clearable
            style="width: 200px"
            @keyup.enter="handleSearch"
          />
        </el-form-item>
        <el-form-item label="服务">
          <el-select v-model="filters.service" placeholder="全部" clearable style="width: 120px">
            <el-option label="SSH" value="ssh" />
            <el-option label="Web" value="web" />
            <el-option label="GDB" value="gdb" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="filters.status" placeholder="全部" clearable style="width: 130px">
            <el-option label="运行中" value="running" />
            <el-option label="已过期" value="expired" />
            <el-option label="已释放" value="released" />
            <el-option label="清理失败" value="cleanup_failed" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="handleSearch">查询</el-button>
          <el-button @click="handleReset">重置</el-button>
          <el-button :icon="Refresh" @click="loadData">刷新</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-tabs v-model="activeServiceTab" class="service-tabs" @tab-change="handleTabChange">
      <el-tab-pane label="全部" name="all" />
      <el-tab-pane label="SSH" name="ssh" />
      <el-tab-pane label="Web" name="web" />
      <el-tab-pane label="GDB" name="gdb" />
    </el-tabs>

    <el-table v-loading="loading" :data="sessions" stripe border>
      <el-table-column prop="device_name" label="设备" min-width="140" />
      <el-table-column label="服务" width="80">
        <template #default="{ row }">
          <el-tag size="small" :type="serviceTagType(row.service)">{{ serviceLabel(row.service) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="公网端口" width="110">
        <template #default="{ row }">
          <el-tag v-if="!isRowPortValid(row)" type="danger" effect="plain">端口异常</el-tag>
          <span v-else>{{ row.public_port }}</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="剩余时间" width="140">
        <template #default="{ row }">
          <span v-if="row.status === 'running'">{{ remainText(row.expire_at) }}</span>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" min-width="170" />
      <el-table-column label="连接命令" min-width="280">
        <template #default="{ row }">
          <div class="connect-cell">
            <span class="connect-text">{{ rowConnectText(row) }}</span>
            <el-button
              link
              type="primary"
              :disabled="!isRowPortValid(row) || !row.connect_text"
              @click="copyText(row.connect_text)"
            >
              复制
            </el-button>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="row.status === 'running' || row.status === 'cleanup_failed'"
            link
            type="danger"
            @click="handleRelease(row)"
          >
            释放
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <div v-if="!loading && !sessions.length" class="empty-hint">
      <el-empty description="暂无符合条件的调试端口记录" />
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, reactive, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getMyTunnels, releaseMyTunnel } from '../../api'
import { DEFAULT_PORT_RANGES, isPortValid } from '../../utils/portPool'

const loading = ref(false)
const sessions = ref([])
const nowTick = ref(Date.now())
const activeServiceTab = ref('all')
const filters = reactive({
  keyword: '',
  service: '',
  status: ''
})
let countdownTimer = null
let refreshTimer = null

function serviceLabel(service) {
  return { ssh: 'SSH', web: 'Web', gdb: 'GDB', temp: 'Temp' }[service] || service
}

function serviceTagType(service) {
  if (service === 'ssh') return 'primary'
  if (service === 'web') return 'success'
  if (service === 'gdb') return 'warning'
  return 'info'
}

function isRowPortValid(row) {
  if (row.port_valid === false) return false
  return isPortValid(row.service, row.public_port, DEFAULT_PORT_RANGES)
}

function rowConnectText(row) {
  if (!isRowPortValid(row)) return '端口异常，无法生成连接命令'
  return row.connect_text || '-'
}

function statusType(status) {
  if (status === 'running') return 'success'
  if (status === 'expired') return 'warning'
  if (status === 'cleanup_failed') return 'danger'
  return 'info'
}

function statusLabel(status) {
  const map = { running: '运行中', expired: '已过期', released: '已释放', cleanup_failed: '清理失败' }
  return map[status] || status
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

function buildQueryParams() {
  const params = {}
  if (filters.keyword.trim()) params.keyword = filters.keyword.trim()
  if (filters.service) params.service = filters.service
  if (filters.status) params.status = filters.status
  if (activeServiceTab.value !== 'all') params.service = activeServiceTab.value
  return params
}

async function loadData() {
  loading.value = true
  try {
    sessions.value = await getMyTunnels(buildQueryParams())
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  loadData()
}

function handleReset() {
  filters.keyword = ''
  filters.service = ''
  filters.status = ''
  activeServiceTab.value = 'all'
  loadData()
}

function handleTabChange(tab) {
  if (tab !== 'all') {
    filters.service = tab
  } else {
    filters.service = ''
  }
  loadData()
}

async function handleRelease(row) {
  await ElMessageBox.confirm('确定释放该调试端口？', '确认')
  await releaseMyTunnel(row.id)
  ElMessage.success('已释放')
  loadData()
}

async function copyText(text) {
  if (!text) return
  await navigator.clipboard.writeText(text)
  ElMessage.success('已复制')
}

onMounted(() => {
  loadData()
  countdownTimer = setInterval(() => {
    nowTick.value = Date.now()
  }, 1000)
  refreshTimer = setInterval(loadData, 120000)
})

onUnmounted(() => {
  if (countdownTimer) clearInterval(countdownTimer)
  if (refreshTimer) clearInterval(refreshTimer)
})
</script>

<style scoped>
.filter-card {
  margin-bottom: 12px;
}

.service-tabs {
  margin-bottom: 12px;
}

.empty-hint {
  margin-top: 24px;
}
</style>
