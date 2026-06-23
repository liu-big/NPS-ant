<template>
  <div v-loading="loading">
    <el-card shadow="never" class="page-card">
      <div class="toolbar">
        <el-input
          v-model="searchRemark"
          placeholder="搜索设备备注"
          clearable
          style="width: 240px"
          :prefix-icon="Search"
        />
        <el-select v-model="statusFilter" placeholder="在线状态" clearable style="width: 140px">
          <el-option label="在线" value="online" />
          <el-option label="离线" value="offline" />
        </el-select>
        <el-select v-model="openFilter" placeholder="连接状态" clearable style="width: 140px">
          <el-option label="开放" :value="true" />
          <el-option label="关闭" :value="false" />
        </el-select>
        <el-button type="primary" :icon="Refresh" @click="loadData">刷新</el-button>
      </div>

      <el-table :data="filteredDevices" stripe border style="width: 100%">
        <el-table-column prop="id" label="设备 ID" width="90" />
        <el-table-column prop="remark" label="设备名称" min-width="180" show-overflow-tooltip />
        <el-table-column prop="version" label="版本" width="100" />
        <el-table-column prop="client_addr" label="客户端地址" width="150" />
        <el-table-column prop="inlet_flow" label="入口流量" width="110" />
        <el-table-column prop="export_flow" label="出口流量" width="110" />
        <el-table-column prop="rate" label="网速" width="100" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === 'online' ? 'success' : 'info'" effect="light">
              {{ row.status === 'online' ? '在线' : '离线' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="连接" width="90">
          <template #default="{ row }">
            <el-tag :type="row.is_open ? 'primary' : 'info'" effect="light">
              {{ row.is_open ? '开放' : '关闭' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link @click="goDetail(row.id)">查看详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh, Search } from '@element-plus/icons-vue'
import { getDevices } from '../api'

const router = useRouter()
const loading = ref(false)
const devices = ref([])
const searchRemark = ref('')
const statusFilter = ref('')
const openFilter = ref(null)

const filteredDevices = computed(() => {
  return devices.value.filter((item) => {
    const matchRemark = !searchRemark.value || item.remark.toLowerCase().includes(searchRemark.value.toLowerCase())
    const matchStatus = !statusFilter.value || item.status === statusFilter.value
    const matchOpen = openFilter.value === null || openFilter.value === '' || item.is_open === openFilter.value
    return matchRemark && matchStatus && matchOpen
  })
})

async function loadData() {
  loading.value = true
  try {
    devices.value = await getDevices()
  } finally {
    loading.value = false
  }
}

function goDetail(id) {
  router.push(`/devices/${id}`)
}

onMounted(loadData)
</script>
