<template>
  <div v-loading="loading">
    <div class="toolbar">
      <el-button type="primary" :icon="Refresh" @click="loadData">刷新</el-button>
    </div>
    <el-table :data="devices" stripe border>
      <el-table-column prop="id" label="设备 ID" width="90" />
      <el-table-column prop="remark" label="备注" min-width="180" show-overflow-tooltip />
      <el-table-column prop="version" label="版本" width="100" />
      <el-table-column prop="client_addr" label="客户端地址" width="150" />
      <el-table-column prop="inlet_flow" label="入口流量" width="110" />
      <el-table-column prop="export_flow" label="出口流量" width="110" />
      <el-table-column prop="rate" label="网速" width="100" />
      <el-table-column label="在线状态" width="100">
        <template #default="{ row }">
          <el-tag :type="row.status === 'online' ? 'success' : 'info'">
            {{ row.status === 'online' ? '在线' : '离线' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="连接" width="90">
        <template #default="{ row }">
          <el-tag :type="row.is_open ? 'primary' : 'info'">
            {{ row.is_open ? '开放' : '关闭' }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { getAdminDevices } from '../../api'

const loading = ref(false)
const devices = ref([])

async function loadData() {
  loading.value = true
  try {
    devices.value = await getAdminDevices()
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
</script>