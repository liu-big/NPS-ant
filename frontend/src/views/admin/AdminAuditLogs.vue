<template>
  <div>
    <el-card shadow="never" class="page-card">
      <el-form :inline="true" :model="filters" class="audit-filters">
        <el-form-item label="关键词">
          <el-input
            v-model="filters.keyword"
            placeholder="详情 / 用户 / 操作"
            clearable
            style="width: 200px"
            @keyup.enter="handleSearch"
          />
        </el-form-item>
        <el-form-item label="用户名">
          <el-input v-model="filters.username" placeholder="用户名" clearable style="width: 140px" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="filters.role" placeholder="全部" clearable style="width: 120px">
            <el-option label="管理员" value="admin" />
            <el-option label="普通用户" value="user" />
            <el-option label="系统" value="system" />
          </el-select>
        </el-form-item>
        <el-form-item label="操作">
          <el-select v-model="filters.action" placeholder="全部" clearable filterable style="width: 180px">
            <el-option v-for="act in actionOptions" :key="act" :label="actionLabel(act)" :value="act" />
          </el-select>
        </el-form-item>
        <el-form-item label="对象类型">
          <el-select v-model="filters.target_type" placeholder="全部" clearable style="width: 140px">
            <el-option v-for="t in targetTypeOptions" :key="t.value" :label="t.label" :value="t.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="时间范围">
          <el-date-picker
            v-model="dateRange"
            type="datetimerange"
            range-separator="至"
            start-placeholder="开始"
            end-placeholder="结束"
            value-format="YYYY-MM-DDTHH:mm:ss"
            style="width: 360px"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="handleSearch">查询</el-button>
          <el-button @click="handleReset">重置</el-button>
          <el-button :icon="Refresh" @click="loadData">刷新</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-table v-loading="loading" :data="logs" stripe border>
      <el-table-column prop="created_at" label="时间" min-width="180">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column prop="username" label="用户" width="120" />
      <el-table-column label="角色" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="roleTagType(row.role)">{{ roleLabel(row.role) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="140">
        <template #default="{ row }">{{ actionLabel(row.action) }}</template>
      </el-table-column>
      <el-table-column prop="target_type" label="对象类型" width="120">
        <template #default="{ row }">{{ targetTypeLabel(row.target_type) }}</template>
      </el-table-column>
      <el-table-column prop="target_id" label="对象 ID" width="100" />
      <el-table-column prop="detail" label="详情" min-width="220" show-overflow-tooltip />
      <el-table-column prop="ip" label="IP" width="130" />
    </el-table>

    <div class="pagination-bar">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[20, 50, 100, 200]"
        layout="total, sizes, prev, pager, next"
        background
        @current-change="loadData"
        @size-change="handleSizeChange"
      />
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { getAuditLogActions, getAuditLogs } from '../../api'

const loading = ref(false)
const logs = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const dateRange = ref(null)
const actionOptions = ref([])

const filters = reactive({
  keyword: '',
  username: '',
  role: '',
  action: '',
  target_type: ''
})

const targetTypeOptions = [
  { value: 'user', label: '用户' },
  { value: 'port_mapping', label: '端口映射' },
  { value: 'device_acl', label: '设备授权(旧)' }
]

const actionLabels = {
  login: '登录',
  logout: '退出登录',
  create_user: '创建用户',
  update_user: '更新用户',
  delete_user: '删除用户',
  reset_password: '重置密码',
  bind_device: '绑定设备',
  unbind_device: '解除绑定',
  create_port_mapping: '申请端口映射',
  release_port_mapping: '释放端口映射',
  port_mapping_auto_expire: '映射自动过期',
  tunnel_cleanup_failed: '端口清理失败'
}

const roleLabels = { admin: '管理员', user: '用户', system: '系统' }
const targetTypeLabels = {
  user: '用户',
  port_mapping: '端口映射',
  device_acl: '设备授权(旧)',
  tunnel_session: '端口映射(历史)'
}

function actionLabel(action) {
  return actionLabels[action] || action
}

function roleLabel(role) {
  return roleLabels[role] || role
}

function targetTypeLabel(type) {
  return targetTypeLabels[type] || type || '-'
}

function roleTagType(role) {
  if (role === 'admin') return 'danger'
  if (role === 'system') return 'warning'
  return 'primary'
}

function formatTime(value) {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return value
  }
}

function buildParams() {
  const params = {
    limit: pageSize.value,
    offset: (page.value - 1) * pageSize.value
  }
  if (filters.keyword) params.keyword = filters.keyword
  if (filters.username) params.username = filters.username
  if (filters.role) params.role = filters.role
  if (filters.action) params.action = filters.action
  if (filters.target_type) params.target_type = filters.target_type
  if (dateRange.value?.[0]) params.start_at = dateRange.value[0]
  if (dateRange.value?.[1]) params.end_at = dateRange.value[1]
  return params
}

async function loadData() {
  loading.value = true
  try {
    const res = await getAuditLogs(buildParams())
    logs.value = res.items || []
    total.value = res.total || 0
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  page.value = 1
  loadData()
}

function handleReset() {
  filters.keyword = ''
  filters.username = ''
  filters.role = ''
  filters.action = ''
  filters.target_type = ''
  dateRange.value = null
  page.value = 1
  loadData()
}

function handleSizeChange() {
  page.value = 1
  loadData()
}

onMounted(async () => {
  try {
    const res = await getAuditLogActions()
    actionOptions.value = res.actions || []
  } catch {
    actionOptions.value = Object.keys(actionLabels)
  }
  loadData()
})
</script>

<style scoped>
.audit-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 0;
}

.pagination-bar {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
