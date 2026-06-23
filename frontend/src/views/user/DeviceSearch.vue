<template>
  <div>
    <el-card shadow="never" class="page-card">
      <template #header>搜索授权设备</template>
      <div class="toolbar">
        <el-input
          v-model="keyword"
          placeholder="请输入设备号 / 设备备注 / 授权码"
          clearable
          style="max-width: 480px"
          @keyup.enter="handleSearch"
        />
        <el-button type="primary" :loading="loading" @click="handleSearch">搜索</el-button>
      </div>
      <el-alert
        title="仅可搜索管理员已授权的设备；调试有效期由管理员分配，申请时无需选择时长。"
        type="info"
        :closable="false"
        show-icon
      />
    </el-card>

    <el-empty v-if="searched && !results.length" description="未找到或无权限" />

    <el-row v-else :gutter="16">
      <el-col v-for="item in results" :key="item.client_id" :xs="24" :md="12" :lg="8">
        <el-card shadow="hover" class="page-card">
          <template #header>
            <div style="display: flex; justify-content: space-between; align-items: center">
              <span>{{ item.device_name || item.remark }}</span>
              <el-tag :type="item.device?.status === 'online' ? 'success' : 'info'">
                {{ item.device?.status === 'online' ? '在线' : '离线' }}
              </el-tag>
            </div>
          </template>
          <el-descriptions :column="1" size="small" border>
            <el-descriptions-item label="设备 ID">{{ item.client_id }}</el-descriptions-item>
            <el-descriptions-item label="备注">{{ item.remark }}</el-descriptions-item>
            <el-descriptions-item label="授权状态">
              <el-tag :type="aclStatusType(item)">{{ item.acl_status_label || item.acl_status }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="调试有效期">
              <el-tag v-if="item.ttl_label && item.ttl_label !== '未设置'" type="warning" effect="plain">
                {{ item.ttl_label }}
              </el-tag>
              <span v-else>未设置</span>
            </el-descriptions-item>
            <el-descriptions-item label="授权截止">
              <span v-if="item.access_expire_at_display || item.access_expire_at">
                {{ item.access_expire_at_display || item.access_expire_at }}（端口可用至此）
              </span>
              <span v-else>未设置，按调试有效期起算</span>
            </el-descriptions-item>
            <el-descriptions-item label="版本">{{ item.device?.version || '-' }}</el-descriptions-item>
          </el-descriptions>
          <div style="margin-top: 16px">
            <el-button
              type="primary"
              :disabled="!item.can_apply"
              @click="openApply(item)"
            >
              申请调试端口
            </el-button>
            <el-text v-if="!item.can_apply" type="danger" size="small" style="margin-left: 8px; display: block; margin-top: 8px">
              {{ item.apply_hint || '当前不可申请' }}
            </el-text>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <el-dialog v-model="applyVisible" title="申请临时调试端口" width="420px">
      <el-form :model="applyForm" label-width="90px">
        <el-form-item label="设备">
          <span>{{ applyForm.device_name }}</span>
        </el-form-item>
        <el-form-item label="服务类型">
          <el-radio-group v-model="applyForm.service">
            <el-radio value="ssh">SSH</el-radio>
            <el-radio value="web">Web</el-radio>
            <el-radio value="gdb">GDB</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="有效期">
          <el-tag v-if="applyForm.access_expire_at" type="warning">
            可用至 {{ applyForm.access_expire_at_display || applyForm.access_expire_at }}（管理员指定截止）
          </el-tag>
          <el-tag v-else type="info">{{ applyForm.ttl_label }}（管理员分配）</el-tag>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="applyVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitApply">确认创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="resultVisible" title="调试通道已创建" width="560px">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="连接命令">
          <div class="connect-cell">
            <span class="connect-text">{{ createdSession?.connect_text }}</span>
            <el-button link type="primary" @click="copyText(createdSession?.connect_text)">复制</el-button>
          </div>
        </el-descriptions-item>
        <el-descriptions-item label="过期时间">{{ createdSession?.expire_at || '永久' }}</el-descriptions-item>
        <el-descriptions-item label="公网端口">{{ createdSession?.public_port }}</el-descriptions-item>
      </el-descriptions>
      <template #footer>
        <el-button type="primary" @click="goMyTunnels">查看我的调试端口</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createMyTunnel, searchMyDevices } from '../../api'

const router = useRouter()
const keyword = ref('')
const loading = ref(false)
const searched = ref(false)
const results = ref([])
const applyVisible = ref(false)
const resultVisible = ref(false)
const creating = ref(false)
const createdSession = ref(null)
const applyForm = reactive({
  client_id: null,
  device_name: '',
  service: 'ssh',
  ttl_label: '',
  access_expire_at: null,
  access_expire_at_display: null
})

async function handleSearch() {
  if (!keyword.value.trim()) {
    ElMessage.warning('请输入搜索关键词')
    return
  }
  loading.value = true
  searched.value = true
  try {
    results.value = await searchMyDevices(keyword.value.trim())
  } catch {
    results.value = []
  } finally {
    loading.value = false
  }
}

function aclStatusType(item) {
  if (item.acl_status === 'active') return 'success'
  if (item.acl_status === 'in_use') return 'warning'
  return 'info'
}

function openApply(item) {
  if (!item.can_apply) {
    ElMessage.warning(item.apply_hint || '当前不可申请调试端口')
    return
  }
  applyForm.client_id = item.client_id
  applyForm.device_name = item.device_name || item.remark
  applyForm.service = 'ssh'
  applyForm.ttl_label = item.ttl_label || '未设置'
  applyForm.access_expire_at = item.access_expire_at || null
  applyForm.access_expire_at_display = item.access_expire_at_display || null
  applyVisible.value = true
}

async function submitApply() {
  creating.value = true
  try {
    createdSession.value = await createMyTunnel({
      client_id: applyForm.client_id,
      service: applyForm.service
    })
    applyVisible.value = false
    resultVisible.value = true
    ElMessage.success('调试端口创建成功')
  } finally {
    creating.value = false
  }
}

function goMyTunnels() {
  resultVisible.value = false
  router.push('/my/tunnels')
}

async function copyText(text) {
  if (!text) return
  await navigator.clipboard.writeText(text)
  ElMessage.success('已复制')
}
</script>
