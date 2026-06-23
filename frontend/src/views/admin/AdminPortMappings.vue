<template>
  <div>
    <el-row :gutter="12" class="stat-row">
      <el-col :xs="12" :sm="8">
        <el-card shadow="never" class="stat-card">
          <div class="stat-value success">{{ runningCount }}</div>
          <div class="stat-label">运行中</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="8">
        <el-card shadow="never" class="stat-card">
          <div class="stat-value muted">{{ historyCount }}</div>
          <div class="stat-label">历史记录</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="8">
        <el-card shadow="never" class="stat-card">
          <div class="stat-value">{{ mappings.length }}</div>
          <div class="stat-label">当前列表</div>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="page-card">
      <el-tabs v-model="activeTab" @tab-change="handleTabChange">
        <el-tab-pane label="运行中" name="running" />
        <el-tab-pane label="历史记录" name="history" />
      </el-tabs>
      <div class="toolbar">
        <el-input
          v-model="filters.keyword"
          placeholder="用户 / 客户端 / 端口"
          clearable
          style="width: 220px"
          @keyup.enter="loadData"
        />
        <el-select
          v-if="activeTab === 'history'"
          v-model="filters.status"
          placeholder="状态"
          clearable
          style="width: 120px"
        >
          <el-option label="已释放" value="deleted" />
          <el-option label="已过期" value="expired" />
          <el-option label="失败" value="failed" />
        </el-select>
        <el-button type="primary" :loading="loading" @click="loadData">查询</el-button>
        <el-button @click="handleReset">重置</el-button>
        <el-button :icon="Refresh" :loading="loading" @click="refreshAll">刷新</el-button>
      </div>

      <el-table v-loading="loading" :data="mappings" stripe border>
        <el-table-column prop="username" label="用户" width="100" />
        <el-table-column prop="device_name" label="客户端" min-width="130" show-overflow-tooltip />
        <el-table-column label="目标" min-width="140">
          <template #default="{ row }">{{ row.target_host }}:{{ row.target_port }}</template>
        </el-table-column>
        <el-table-column label="公网映射" min-width="150">
          <template #default="{ row }">{{ row.public_host }}:{{ row.public_port }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" effect="plain">
              {{ row.status_label || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column v-if="activeTab === 'running'" label="剩余" width="120">
          <template #default="{ row }">{{ row.remaining_label || '-' }}</template>
        </el-table-column>
        <el-table-column v-if="activeTab === 'running'" label="到期" min-width="165">
          <template #default="{ row }">{{ row.expire_at_display || '永久' }}</template>
        </el-table-column>
        <el-table-column v-if="activeTab === 'history'" label="结束时间" min-width="165">
          <template #default="{ row }">{{ row.ended_at_display || '-' }}</template>
        </el-table-column>
        <el-table-column v-if="activeTab === 'history'" label="结束原因" width="120">
          <template #default="{ row }">{{ row.release_reason_label || '-' }}</template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="165">
          <template #default="{ row }">{{ row.created_at_display || row.created_at }}</template>
        </el-table-column>
        <el-table-column v-if="activeTab === 'running'" label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button link type="danger" @click="handleRelease(row)">强制释放</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="!loading && !mappings.length" :description="emptyText" />
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getAdminPortMappings, releaseAdminPortMapping } from '../../api'

const loading = ref(false)
const mappings = ref([])
const runningCount = ref(0)
const historyCount = ref(0)
const activeTab = ref('running')
const filters = reactive({ keyword: '', status: '' })

const emptyText = computed(() =>
  activeTab.value === 'running' ? '暂无运行中的端口映射' : '暂无历史记录'
)

function statusType(status) {
  if (status === 'running') return 'success'
  if (status === 'expired') return 'warning'
  if (status === 'failed') return 'danger'
  return 'info'
}

function buildParams() {
  const params = { history: activeTab.value === 'history' }
  if (filters.keyword.trim()) params.keyword = filters.keyword.trim()
  if (activeTab.value === 'history' && filters.status) params.status = filters.status
  return params
}

async function loadCounts() {
  const [running, history] = await Promise.all([
    getAdminPortMappings({ history: false }),
    getAdminPortMappings({ history: true })
  ])
  runningCount.value = running.length
  historyCount.value = history.length
}

async function loadData() {
  loading.value = true
  try {
    mappings.value = await getAdminPortMappings(buildParams())
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
  await ElMessageBox.confirm(
    `强制释放 ${row.public_host}:${row.public_port}（用户 ${row.username}）？`,
    '确认'
  )
  await releaseAdminPortMapping(row.id)
  ElMessage.success('已释放')
  refreshAll()
}

onMounted(refreshAll)
</script>

<style scoped>
.stat-row {
  margin-bottom: 12px;
}

.stat-card {
  text-align: center;
  padding: 8px 0;
}

.stat-value {
  font-size: 26px;
  font-weight: 600;
  color: #303133;
}

.stat-value.success {
  color: #67c23a;
}

.stat-value.muted {
  color: #909399;
}

.stat-label {
  margin-top: 4px;
  font-size: 13px;
  color: #909399;
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
</style>
