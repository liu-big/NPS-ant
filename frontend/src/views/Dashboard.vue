<template>
  <div v-loading="loading">
    <el-row :gutter="16">
      <el-col v-for="item in cards" :key="item.label" :xs="24" :sm="12" :md="8" :lg="4">
        <el-card class="stat-card page-card" shadow="hover">
          <div class="stat-label">{{ item.label }}</div>
          <div class="stat-value" :style="{ color: item.color }">{{ item.value }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" style="margin-top: 16px">
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center">
          <span>管理概览</span>
          <el-button :icon="Refresh" @click="loadData">刷新</el-button>
        </div>
      </template>
      <el-alert
        title="管理员可查看 NPS 设备、管理用户、监控端口映射与审计日志。"
        type="info"
        :closable="false"
        show-icon
      />
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { getDashboardSummary } from '../api'

const loading = ref(false)
const summary = ref({
  total_devices: 0,
  online_devices: 0,
  offline_devices: 0,
  open_connections: 0,
  total_inlet_flow: '0B',
  total_export_flow: '0B',
  active_tunnel_sessions: 0
})

const cards = computed(() => [
  { label: '设备总数', value: summary.value.total_devices, color: '#1677ff' },
  { label: '在线设备', value: summary.value.online_devices, color: '#52c41a' },
  { label: '离线设备', value: summary.value.offline_devices, color: '#8c8c8c' },
  { label: '开放通道', value: summary.value.open_connections, color: '#1677ff' },
  { label: '活跃端口映射', value: summary.value.active_tunnel_sessions, color: '#722ed1' },
  { label: '总入口流量', value: summary.value.total_inlet_flow, color: '#722ed1' }
])

async function loadData() {
  loading.value = true
  try {
    summary.value = await getDashboardSummary()
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
</script>

