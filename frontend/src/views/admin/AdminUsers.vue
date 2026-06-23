<template>
  <div>
    <el-row :gutter="12" class="stat-row">
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-value">{{ stats.total }}</div>
          <div class="stat-label">用户总数</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-value success">{{ stats.active }}</div>
          <div class="stat-label">启用</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-value muted">{{ stats.disabled }}</div>
          <div class="stat-label">已禁用</div>
        </el-card>
      </el-col>
      <el-col :xs="12" :sm="6">
        <el-card shadow="never" class="stat-card">
          <div class="stat-value danger">{{ stats.admins }}</div>
          <div class="stat-label">管理员</div>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="page-card">
      <div class="toolbar">
        <el-form :inline="true" :model="filters" class="filter-form">
          <el-form-item label="关键词">
            <el-input
              v-model="filters.keyword"
              placeholder="用户名"
              clearable
              style="width: 160px"
            />
          </el-form-item>
          <el-form-item label="角色">
            <el-select v-model="filters.role" placeholder="全部" clearable style="width: 120px">
              <el-option label="管理员" value="admin" />
              <el-option label="普通用户" value="user" />
            </el-select>
          </el-form-item>
          <el-form-item label="状态">
            <el-select v-model="filters.status" placeholder="全部" clearable style="width: 120px">
              <el-option label="启用" value="active" />
              <el-option label="禁用" value="disabled" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button @click="handleResetFilter">重置</el-button>
          </el-form-item>
        </el-form>
        <div class="toolbar-actions">
          <el-button type="primary" @click="openCreate">创建用户</el-button>
          <el-button :icon="Refresh" :loading="loading" @click="loadData">刷新</el-button>
        </div>
      </div>

      <el-table v-loading="loading" :data="pagedUsers" stripe border>
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column label="用户名" min-width="140">
          <template #default="{ row }">
            <span>{{ row.username }}</span>
            <el-tag v-if="isSelf(row)" size="small" type="warning" effect="plain" class="self-tag">当前</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="角色" width="110">
          <template #default="{ row }">
            <el-tag :type="row.role === 'admin' ? 'danger' : 'primary'" effect="plain">
              {{ roleLabel(row.role) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'active' ? 'success' : 'info'" effect="plain">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="170">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="更新时间" min-width="170">
          <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="260" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="warning" @click="openReset(row)">重置密码</el-button>
            <el-button
              v-if="!isSelf(row)"
              link
              :type="row.status === 'active' ? 'info' : 'success'"
              @click="toggleStatus(row)"
            >
              {{ row.status === 'active' ? '禁用' : '启用' }}
            </el-button>
            <el-button v-if="!isSelf(row)" link type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-bar">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="filteredUsers.length"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next"
          background
        />
      </div>

      <el-empty v-if="!loading && !filteredUsers.length" description="暂无符合条件的用户" />
    </el-card>

    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="440px" destroy-on-close>
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="88px">
        <el-form-item v-if="!editingId" label="用户名" prop="username">
          <el-input v-model="form.username" placeholder="3-32 位字母数字下划线" maxlength="32" />
        </el-form-item>
        <el-form-item v-if="!editingId" label="密码" prop="password">
          <el-input v-model="form.password" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
        <el-form-item v-else label="用户名">
          <el-input :model-value="form.username" disabled />
        </el-form-item>
        <el-form-item label="角色" prop="role">
          <el-select v-model="form.role" style="width: 100%" :disabled="isEditingSelf">
            <el-option label="普通用户" value="user" />
            <el-option label="管理员" value="admin" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="editingId" label="状态" prop="status">
          <el-radio-group v-model="form.status" :disabled="isEditingSelf">
            <el-radio value="active">启用</el-radio>
            <el-radio value="disabled">禁用</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submitForm">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="resetVisible" title="重置密码" width="440px" destroy-on-close>
      <p class="reset-hint">为用户 <strong>{{ resetUsername }}</strong> 设置新密码</p>
      <el-form ref="resetFormRef" :model="resetForm" :rules="resetRules" label-width="88px">
        <el-form-item label="新密码" prop="password">
          <el-input v-model="resetForm.password" type="password" show-password placeholder="至少 6 位" />
        </el-form-item>
        <el-form-item label="确认密码" prop="confirm">
          <el-input v-model="resetForm.confirm" type="password" show-password placeholder="再次输入" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="resetVisible = false">取消</el-button>
        <el-button type="primary" :loading="resetting" @click="submitReset">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createUser, deleteUser, getAdminUsers, getStoredUser, resetUserPassword, updateUser } from '../../api'

const loading = ref(false)
const submitting = ref(false)
const resetting = ref(false)
const users = ref([])
const dialogVisible = ref(false)
const resetVisible = ref(false)
const dialogTitle = ref('创建用户')
const editingId = ref(null)
const resetUserId = ref(null)
const resetUsername = ref('')
const page = ref(1)
const pageSize = ref(20)
const formRef = ref(null)
const resetFormRef = ref(null)
const currentUser = computed(() => getStoredUser())

const filters = reactive({
  keyword: '',
  role: '',
  status: ''
})

const form = reactive({ username: '', password: '', role: 'user', status: 'active' })
const resetForm = reactive({ password: '', confirm: '' })

const usernamePattern = /^[a-zA-Z0-9_]{3,32}$/

const formRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { pattern: usernamePattern, message: '3-32 位字母、数字或下划线', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 位', trigger: 'blur' }
  ],
  role: [{ required: true, message: '请选择角色', trigger: 'change' }]
}

const resetRules = {
  password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 位', trigger: 'blur' }
  ],
  confirm: [
    { required: true, message: '请确认密码', trigger: 'blur' },
    {
      validator: (_rule, value, callback) => {
        if (value !== resetForm.password) callback(new Error('两次密码不一致'))
        else callback()
      },
      trigger: 'blur'
    }
  ]
}

const filteredUsers = computed(() => {
  const kw = filters.keyword.trim().toLowerCase()
  return users.value.filter((u) => {
    if (kw && !u.username.toLowerCase().includes(kw)) return false
    if (filters.role && u.role !== filters.role) return false
    if (filters.status && u.status !== filters.status) return false
    return true
  })
})

const pagedUsers = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredUsers.value.slice(start, start + pageSize.value)
})

const stats = computed(() => ({
  total: users.value.length,
  active: users.value.filter((u) => u.status === 'active').length,
  disabled: users.value.filter((u) => u.status === 'disabled').length,
  admins: users.value.filter((u) => u.role === 'admin').length
}))

const isEditingSelf = computed(() => editingId.value && editingId.value === currentUser.value?.id)

function isSelf(row) {
  return row.id === currentUser.value?.id
}

function roleLabel(role) {
  return { admin: '管理员', user: '普通用户' }[role] || role
}

function statusLabel(status) {
  return { active: '启用', disabled: '禁用' }[status] || status
}

function formatTime(value) {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return value
  }
}

async function loadData() {
  loading.value = true
  try {
    users.value = await getAdminUsers()
  } finally {
    loading.value = false
  }
}

function handleResetFilter() {
  filters.keyword = ''
  filters.role = ''
  filters.status = ''
  page.value = 1
}

function openCreate() {
  editingId.value = null
  dialogTitle.value = '创建用户'
  Object.assign(form, { username: '', password: '', role: 'user', status: 'active' })
  dialogVisible.value = true
}

function openEdit(row) {
  editingId.value = row.id
  dialogTitle.value = '编辑用户'
  Object.assign(form, {
    username: row.username,
    password: '',
    role: row.role,
    status: row.status
  })
  dialogVisible.value = true
}

function openReset(row) {
  resetUserId.value = row.id
  resetUsername.value = row.username
  resetForm.password = ''
  resetForm.confirm = ''
  resetVisible.value = true
}

async function submitForm() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    if (editingId.value) {
      await updateUser(editingId.value, { role: form.role, status: form.status })
      ElMessage.success('已更新')
    } else {
      await createUser({
        username: form.username.trim(),
        password: form.password,
        role: form.role
      })
      ElMessage.success('用户已创建')
    }
    dialogVisible.value = false
    loadData()
  } finally {
    submitting.value = false
  }
}

async function submitReset() {
  const valid = await resetFormRef.value?.validate().catch(() => false)
  if (!valid) return
  resetting.value = true
  try {
    await resetUserPassword(resetUserId.value, resetForm.password)
    ElMessage.success('密码已重置')
    resetVisible.value = false
  } finally {
    resetting.value = false
  }
}

async function toggleStatus(row) {
  const next = row.status === 'active' ? 'disabled' : 'active'
  const action = next === 'disabled' ? '禁用' : '启用'
  await ElMessageBox.confirm(`确定${action}用户 ${row.username}？`, '确认')
  await updateUser(row.id, { status: next })
  ElMessage.success(`已${action}`)
  loadData()
}

async function handleDelete(row) {
  await ElMessageBox.confirm(
    `确定删除用户 ${row.username}？其设备授权与映射记录可能受影响。`,
    '确认删除',
    { type: 'warning' }
  )
  await deleteUser(row.id)
  ElMessage.success('已删除')
  loadData()
}

onMounted(loadData)
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
  font-size: 28px;
  font-weight: 600;
  color: #303133;
  line-height: 1.2;
}

.stat-value.success {
  color: #67c23a;
}

.stat-value.muted {
  color: #909399;
}

.stat-value.danger {
  color: #f56c6c;
}

.stat-label {
  margin-top: 4px;
  font-size: 13px;
  color: #909399;
}

.toolbar {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  margin-bottom: 12px;
}

.filter-form {
  flex: 1;
}

.toolbar-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.self-tag {
  margin-left: 6px;
  vertical-align: middle;
}

.pagination-bar {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}

.reset-hint {
  margin: 0 0 16px;
  color: #606266;
}
</style>
