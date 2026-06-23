<template>
  <div v-loading="loading">
    <el-page-header @back="goBack">
      <template #content>
        <span style="font-weight: 600">设备详情</span>
      </template>
    </el-page-header>

    <el-row :gutter="16" style="margin-top: 16px">
      <el-col :xs="24" :lg="10">
        <el-card shadow="never" class="page-card">
          <div class="detail-section">
            <h3>基础信息</h3>
            <el-descriptions :column="1" border>
              <el-descriptions-item label="设备名称">{{ device.remark || '-' }}</el-descriptions-item>
              <el-descriptions-item label="客户端 ID">{{ device.id || '-' }}</el-descriptions-item>
              <el-descriptions-item label="版本">{{ device.version || '-' }}</el-descriptions-item>
              <el-descriptions-item label="客户端地址">{{ device.client_addr || '-' }}</el-descriptions-item>
              <el-descriptions-item label="在线状态">
                <el-tag :type="device.status === 'online' ? 'success' : 'info'">
                  {{ device.status === 'online' ? '在线' : '离线' }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="连接状态">
                <el-tag :type="device.is_open ? 'primary' : 'info'">
                  {{ device.is_open ? '开放' : '关闭' }}
                </el-tag>
              </el-descriptions-item>
            </el-descriptions>
          </div>

          <div class="detail-section">
            <h3>流量统计</h3>
            <el-descriptions :column="1" border>
              <el-descriptions-item label="入口流量">{{ device.inlet_flow || '0B' }}</el-descriptions-item>
              <el-descriptions-item label="出口流量">{{ device.export_flow || '0B' }}</el-descriptions-item>
              <el-descriptions-item label="当前网速">{{ device.rate || '0B/S' }}</el-descriptions-item>
            </el-descriptions>
          </div>
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="14">
        <el-card shadow="never" class="page-card">
          <template #header>
            <div style="display: flex; justify-content: space-between; align-items: center">
              <span>隧道列表</span>
              <el-button :icon="Refresh" @click="loadData">刷新</el-button>
            </div>
          </template>

          <el-table :data="tunnels" stripe border style="width: 100%">
            <el-table-column prop="id" label="隧道 ID" width="90" />
            <el-table-column prop="remark" label="备注" min-width="160" show-overflow-tooltip />
            <el-table-column prop="mode" label="模式" width="80" />
            <el-table-column prop="server_port" label="公网端口" width="100" />
            <el-table-column prop="target" label="目标地址" min-width="140" show-overflow-tooltip />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="row.status === 'running' ? 'success' : 'info'">
                  {{ row.status === 'running' ? '运行中' : '已停止' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="客户端状态" width="110">
              <template #default="{ row }">
                <el-tag :type="row.client_status === 'online' ? 'success' : 'info'">
                  {{ row.client_status === 'online' ? '在线' : '离线' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="连接命令" min-width="260">
              <template #default="{ row }">
                <div class="connect-cell">
                  <span class="connect-text">{{ row.connect_text || '-' }}</span>
                  <el-button
                    v-if="row.connect_text"
                    type="primary"
                    link
                    :icon="DocumentCopy"
                    @click="copyText(row.connect_text)"
                  >
                    复制
                  </el-button>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { DocumentCopy, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getDevice, getDeviceTunnels } from '../api'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const device = reactive({
  id: 0,
  remark: '',
  version: '',
  client_addr: '',
  inlet_flow: '',
  export_flow: '',
  rate: '',
  status: 'offline',
  is_open: false
})
const tunnels = ref([])

async function loadData() {
  loading.value = true
  try {
    const clientId = route.params.id
    const [deviceData, tunnelData] = await Promise.all([
      getDevice(clientId),
      getDeviceTunnels(clientId)
    ])
    Object.assign(device, deviceData)
    tunnels.value = tunnelData
  } finally {
    loading.value = false
  }
}

function goBack() {
  router.push('/devices')
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.error('复制失败，请手动复制')
  }
}

onMounted(loadData)
</script>
