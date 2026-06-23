<template>
  <div>
    <el-card shadow="never" class="page-card">
      <template #header>绑定设备授权</template>
      <el-form :inline="true" :model="bindForm" class="bind-form">
        <el-form-item label="用户">
          <el-select v-model="bindForm.user_id" filterable placeholder="选择用户" style="width: 160px">
            <el-option v-for="u in userOptions" :key="u.id" :label="u.username" :value="u.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="设备 ID">
          <el-input v-model.number="bindForm.client_id" placeholder="NPS 客户端 ID" style="width: 120px" />
        </el-form-item>
        <el-form-item label="设备名称">
          <el-input v-model="bindForm.device_name" placeholder="如 ubuntu-dev-04" style="width: 160px" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="bindForm.remark" placeholder="NPS 设备备注" style="width: 160px" />
        </el-form-item>
        <el-form-item label="调试有效期">
          <el-select
            v-model="bindForm.ttl_key"
            clearable
            placeholder="请填写时间"
            style="width: 150px"
          >
            <el-option v-for="opt in ttlOptions" :key="opt.key" :label="opt.label" :value="opt.key" />
          </el-select>
        </el-form-item>
        <el-form-item label="授权截止">
          <el-date-picker
            v-model="bindForm.access_expire_at"
            type="datetime"
            placeholder="请填写时间"
            value-format="YYYY-MM-DDTHH:mm:ss"
            clearable
            style="width: 200px"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="binding" @click="handleBind">绑定并生成授权码</el-button>
        </el-form-item>
      </el-form>
      <el-alert
        title="「调试有效期」与「授权截止」至少填一项；仅填授权截止时，端口可用到该时刻；仅填调试有效期时，自用户申请起算。"
        type="info"
        :closable="false"
        show-icon
      />
    </el-card>

    <el-table v-loading="loading" :data="aclList" stripe border>
      <el-table-column prop="username" label="用户" width="100" />
      <el-table-column prop="client_id" label="设备 ID" width="90" />
      <el-table-column prop="device_name" label="设备名称" min-width="130" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)">{{ row.status_label || row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="调试有效期" min-width="180">
        <template #default="{ row }">{{ row.ttl_label || '未设置' }}</template>
      </el-table-column>
      <el-table-column label="授权截止" width="180">
        <template #default="{ row }">
          {{ row.access_expire_at_display || row.access_expire_at || '未设置' }}
        </template>
      </el-table-column>
      <el-table-column label="结束时间" width="160">
        <template #default="{ row }">{{ row.released_at || '-' }}</template>
      </el-table-column>
      <el-table-column prop="access_code" label="授权码" width="150">
        <template #default="{ row }">
          <span class="connect-text">{{ row.access_code }}</span>
          <el-button link type="primary" @click="copyText(row.access_code)">复制</el-button>
        </template>
      </el-table-column>
      <el-table-column prop="created_at" label="创建时间" min-width="160" />
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button
            v-if="row.status === 'completed'"
            link
            type="primary"
            @click="openReassign(row)"
          >
            重新分配
          </el-button>
          <el-button link type="danger" @click="handleUnbind(row)">解除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="reassignVisible" title="重新分配授权" width="420px">
      <el-form label-width="100px">
        <el-form-item label="设备">
          <span>{{ reassignTarget?.device_name || reassignTarget?.remark }}</span>
        </el-form-item>
        <el-form-item label="调试有效期">
          <el-select v-model="reassignForm.ttl_key" clearable placeholder="请填写时间" style="width: 100%">
            <el-option v-for="opt in ttlOptions" :key="opt.key" :label="opt.label" :value="opt.key" />
          </el-select>
        </el-form-item>
        <el-form-item label="授权截止">
          <el-date-picker
            v-model="reassignForm.access_expire_at"
            type="datetime"
            placeholder="请填写时间"
            value-format="YYYY-MM-DDTHH:mm:ss"
            clearable
            style="width: 100%"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="reassignVisible = false">取消</el-button>
        <el-button type="primary" :loading="reassigning" @click="submitReassign">确认重新分配</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createDeviceAcl,
  deleteDeviceAcl,
  getAdminUsers,
  getDeviceAcl,
  getPortalConfig,
  reassignDeviceAcl
} from '../../api'

const loading = ref(false)
const binding = ref(false)
const reassigning = ref(false)
const aclList = ref([])
const userOptions = ref([])
const ttlOptions = ref([])
const reassignVisible = ref(false)
const reassignTarget = ref(null)
const bindForm = reactive({
  user_id: null,
  client_id: null,
  device_name: '',
  remark: '',
  ttl_key: null,
  access_expire_at: null
})
const reassignForm = reactive({
  ttl_key: null,
  access_expire_at: null
})

function statusTagType(status) {
  if (status === 'active') return 'success'
  if (status === 'in_use') return 'warning'
  if (status === 'completed') return 'info'
  return 'info'
}

async function loadTtlOptions() {
  const cfg = await getPortalConfig()
  ttlOptions.value = cfg.ttl_options || []
}

async function loadData() {
  loading.value = true
  try {
    ;[aclList.value, userOptions.value] = await Promise.all([getDeviceAcl(), getAdminUsers()])
  } finally {
    loading.value = false
  }
}

async function handleBind() {
  if (!bindForm.user_id || !bindForm.client_id) {
    ElMessage.warning('请选择用户并填写设备 ID')
    return
  }
  if (!bindForm.ttl_key && !bindForm.access_expire_at) {
    ElMessage.warning('请填写「调试有效期」或「授权截止」至少一项')
    return
  }
  binding.value = true
  try {
    const payload = {
      user_id: bindForm.user_id,
      client_id: bindForm.client_id,
      device_name: bindForm.device_name,
      remark: bindForm.remark,
      ttl_key: bindForm.ttl_key || null,
      access_expire_at: bindForm.access_expire_at || null
    }
    const res = await createDeviceAcl(payload)
    ElMessage.success(`绑定成功，授权码：${res.access_code}`)
    loadData()
  } finally {
    binding.value = false
  }
}

function openReassign(row) {
  reassignTarget.value = row
  reassignForm.ttl_key = row.ttl_key || null
  reassignForm.access_expire_at = row.access_expire_at || null
  reassignVisible.value = true
}

async function submitReassign() {
  if (!reassignTarget.value) return
  if (!reassignForm.ttl_key && !reassignForm.access_expire_at) {
    ElMessage.warning('请填写「调试有效期」或「授权截止」至少一项')
    return
  }
  reassigning.value = true
  try {
    await reassignDeviceAcl(reassignTarget.value.id, {
      ttl_key: reassignForm.ttl_key || null,
      access_expire_at: reassignForm.access_expire_at || null
    })
    ElMessage.success('已重新分配，用户可再次申请调试端口')
    reassignVisible.value = false
    loadData()
  } finally {
    reassigning.value = false
  }
}

async function handleUnbind(row) {
  await ElMessageBox.confirm(
    '确定解除该设备授权？将同时释放用户在该设备上运行中的调试端口。',
    '确认'
  )
  await deleteDeviceAcl(row.id)
  ElMessage.success('已解除')
  loadData()
}

async function copyText(text) {
  await navigator.clipboard.writeText(text)
  ElMessage.success('已复制')
}

onMounted(async () => {
  await loadTtlOptions()
  loadData()
})
</script>

<style scoped>
.bind-form {
  margin-bottom: 12px;
}
</style>
