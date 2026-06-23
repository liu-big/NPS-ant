<template>
  <div>
    <el-card shadow="never" class="page-card">
      <template #header>申请端口映射</template>
      <el-form :model="form" label-width="100px" style="max-width: 560px">
        <el-form-item label="客户端设备" required>
          <div class="device-search">
            <el-input
              v-model="deviceKeyword"
              placeholder="搜索设备备注名或 ID，如 auto-ubuntu-dev-02"
              clearable
              @keyup.enter="handleSearchDevice"
            />
            <el-button type="primary" :loading="searching" @click="handleSearchDevice">搜索</el-button>
          </div>
          <el-table
            v-if="deviceResults.length"
            :data="deviceResults"
            size="small"
            highlight-current-row
            class="device-table"
            @current-change="handleSelectDevice"
          >
            <el-table-column label="ID" width="70" prop="client_id" />
            <el-table-column label="备注名" min-width="180" prop="remark" />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="row.status === 'online' ? 'success' : 'info'" size="small">
                  {{ row.status === 'online' ? '在线' : '离线' }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
          <div v-if="selectedDevice" class="selected-device">
            已选：<strong>{{ selectedDevice.remark }}</strong>（ID: {{ selectedDevice.client_id }}）
          </div>
          <div v-else-if="searchedOnce && !deviceResults.length" class="hint-text">未找到设备，请检查备注名或 ID</div>
        </el-form-item>
        <el-form-item label="目标地址">
          <el-input v-model="form.target_host" placeholder="留空默认 127.0.0.1（客户端本机）" clearable />
        </el-form-item>
        <el-form-item label="目标端口" required>
          <el-input-number v-model="form.target_port" :min="1" :max="65535" style="width: 100%" />
        </el-form-item>
        <el-form-item label="使用时长" required>
          <el-select v-model="form.ttl_minutes" style="width: 100%">
            <el-option
              v-for="opt in ttlOptions"
              :key="opt.minutes ?? 'permanent'"
              :label="opt.label"
              :value="opt.minutes"
            />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="submitting" :disabled="!form.client_id" @click="handleSubmit">
            申请映射
          </el-button>
        </el-form-item>
      </el-form>
      <el-alert
        title="目标地址留空时将映射到客户端本机 127.0.0.1；默认使用时长 12 小时，也可选择永久。"
        type="info"
        :closable="false"
        show-icon
      />
    </el-card>

    <el-dialog v-model="resultVisible" title="映射创建成功" width="520px">
      <el-descriptions v-if="created" :column="1" border>
        <el-descriptions-item label="客户端">{{ created.device_name || created.client_id }}</el-descriptions-item>
        <el-descriptions-item label="公网地址">{{ created.public_host }}</el-descriptions-item>
        <el-descriptions-item label="公网端口">{{ created.public_port }}</el-descriptions-item>
        <el-descriptions-item label="目标">{{ created.target_host }}:{{ created.target_port }}</el-descriptions-item>
        <el-descriptions-item label="连接地址">
          <span class="connect-text">{{ created.connect_text }}</span>
          <el-button link type="primary" @click="copyText(created.connect_text)">复制</el-button>
        </el-descriptions-item>
        <el-descriptions-item label="到期时间">
          {{ created.expire_at_display || '永久' }}
        </el-descriptions-item>
      </el-descriptions>
      <template #footer>
        <el-button @click="resultVisible = false">关闭</el-button>
        <el-button type="primary" @click="goMyMappings">查看我的映射</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createPortMapping, getPortalConfig, searchMappingClients } from '../../api'

const router = useRouter()
const submitting = ref(false)
const searching = ref(false)
const searchedOnce = ref(false)
const resultVisible = ref(false)
const created = ref(null)
const ttlOptions = ref([])
const deviceKeyword = ref('')
const deviceResults = ref([])
const selectedDevice = ref(null)

const form = reactive({
  client_id: null,
  target_host: '',
  target_port: 22,
  ttl_minutes: 720
})

async function loadConfig() {
  const cfg = await getPortalConfig()
  ttlOptions.value = cfg.user_ttl_options || []
  const defaultTtl = cfg.default_ttl_minutes ?? 720
  const hasDefault = ttlOptions.value.some((o) => o.minutes === defaultTtl)
  form.ttl_minutes = hasDefault ? defaultTtl : ttlOptions.value[0]?.minutes ?? 720
}

async function handleSearchDevice() {
  const kw = deviceKeyword.value.trim()
  if (!kw) {
    ElMessage.warning('请输入设备备注名或 ID')
    return
  }
  searching.value = true
  searchedOnce.value = true
  try {
    deviceResults.value = await searchMappingClients(kw)
    selectedDevice.value = null
    form.client_id = null
    if (deviceResults.value.length === 1) {
      handleSelectDevice(deviceResults.value[0])
    }
  } finally {
    searching.value = false
  }
}

function handleSelectDevice(row) {
  if (!row) return
  selectedDevice.value = row
  form.client_id = row.client_id
}

async function handleSubmit() {
  if (!form.client_id) {
    ElMessage.warning('请先搜索并选择客户端设备')
    return
  }
  submitting.value = true
  try {
    const payload = {
      client_id: form.client_id,
      target_port: form.target_port,
      ttl_minutes: form.ttl_minutes
    }
    const host = form.target_host?.trim()
    if (host) payload.target_host = host
    created.value = await createPortMapping(payload)
    resultVisible.value = true
    ElMessage.success('端口映射创建成功')
  } finally {
    submitting.value = false
  }
}

function goMyMappings() {
  resultVisible.value = false
  router.push('/my/port-mappings')
}

async function copyText(text) {
  if (!text) return
  await navigator.clipboard.writeText(text)
  ElMessage.success('已复制')
}

onMounted(loadConfig)
</script>

<style scoped>
.device-search {
  display: flex;
  gap: 8px;
  width: 100%;
  margin-bottom: 8px;
}

.device-table {
  width: 100%;
  margin-top: 8px;
}

.selected-device {
  margin-top: 8px;
  color: #409eff;
}

.hint-text {
  margin-top: 8px;
  color: #909399;
  font-size: 13px;
}

.connect-text {
  word-break: break-all;
  margin-right: 8px;
}
</style>
