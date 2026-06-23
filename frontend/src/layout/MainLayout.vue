<template>
  <el-container class="layout-container">
    <el-aside width="220px" class="layout-aside">
      <div class="logo">
        <el-icon><Monitor /></el-icon>
        <span>NPS 调试门户</span>
      </div>
      <el-menu
        :default-active="activeMenu"
        background-color="#001529"
        text-color="#bfbfbf"
        active-text-color="#ffffff"
        router
      >
        <template v-if="isAdmin">
          <el-menu-item index="/dashboard">
            <el-icon><DataAnalysis /></el-icon>
            <span>概览</span>
          </el-menu-item>
          <el-menu-item index="/admin/devices">
            <el-icon><Cpu /></el-icon>
            <span>设备管理</span>
          </el-menu-item>
          <el-menu-item index="/admin/users">
            <el-icon><User /></el-icon>
            <span>用户管理</span>
          </el-menu-item>
          <el-menu-item index="/admin/port-mappings">
            <el-icon><Connection /></el-icon>
            <span>端口映射</span>
          </el-menu-item>
          <el-menu-item index="/admin/audit-logs">
            <el-icon><Document /></el-icon>
            <span>审计日志</span>
          </el-menu-item>
        </template>
        <template v-else>
          <el-menu-item index="/port-mapping/apply">
            <el-icon><Plus /></el-icon>
            <span>申请映射</span>
          </el-menu-item>
          <el-menu-item index="/my/port-mappings">
            <el-icon><Connection /></el-icon>
            <span>我的映射</span>
          </el-menu-item>
        </template>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="layout-header">
        <div class="header-title">NPS 远程调试门户</div>
        <div class="header-actions">
          <el-tag type="info" effect="plain">{{ userLabel }}</el-tag>
          <el-button type="danger" link @click="handleLogout">
            <el-icon><SwitchButton /></el-icon>
            退出登录
          </el-button>
        </div>
      </el-header>

      <el-main class="layout-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { clearAuth, getStoredUser, logout } from '../api'

const route = useRoute()
const router = useRouter()
const user = computed(() => getStoredUser())
const isAdmin = computed(() => user.value?.role === 'admin')

const userLabel = computed(() => {
  if (!user.value) return ''
  return user.value.role === 'admin' ? `管理员 · ${user.value.username}` : user.value.username
})

const activeMenu = computed(() => {
  if (route.path.startsWith('/admin/devices')) return '/admin/devices'
  if (route.path.startsWith('/my/port-mappings')) return '/my/port-mappings'
  if (route.path.startsWith('/port-mapping')) return '/port-mapping/apply'
  if (route.path.startsWith('/admin/port-mappings')) return '/admin/port-mappings'
  return route.path
})

async function handleLogout() {
  try {
    await logout()
  } catch {
    // ignore
  }
  clearAuth()
  router.push('/login')
}
</script>

<style scoped>
.layout-container {
  min-height: 100vh;
}

.layout-aside {
  background: var(--portal-sidebar);
  color: #fff;
}

.logo {
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #fff;
  font-size: 18px;
  font-weight: 600;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.layout-header {
  background: var(--portal-header);
  display: flex;
  align-items: center;
  justify-content: space-between;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.08);
  padding: 0 24px;
}

.header-title {
  font-size: 18px;
  font-weight: 600;
  color: #1f1f1f;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.layout-main {
  padding: 20px;
}

@media (max-width: 768px) {
  .layout-aside {
    width: 64px !important;
  }

  .logo span {
    display: none;
  }
}
</style>
