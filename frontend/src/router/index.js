import { createRouter, createWebHistory } from 'vue-router'
import Login from '../views/Login.vue'
import MainLayout from '../layout/MainLayout.vue'
import { getStoredUser } from '../api'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'Login',
      component: Login,
      meta: { public: true }
    },
    {
      path: '/',
      component: MainLayout,
      redirect: () => {
        const user = getStoredUser()
        return user?.role === 'admin' ? '/dashboard' : '/port-mapping/apply'
      },
      children: [
        {
          path: 'dashboard',
          name: 'Dashboard',
          component: () => import('../views/Dashboard.vue'),
          meta: { title: '概览', roles: ['admin'] }
        },
        {
          path: 'admin/devices',
          name: 'AdminDevices',
          component: () => import('../views/admin/AdminDevices.vue'),
          meta: { title: '设备管理', roles: ['admin'] }
        },
        {
          path: 'admin/users',
          name: 'AdminUsers',
          component: () => import('../views/admin/AdminUsers.vue'),
          meta: { title: '用户管理', roles: ['admin'] }
        },
        {
          path: 'admin/port-mappings',
          name: 'AdminPortMappings',
          component: () => import('../views/admin/AdminPortMappings.vue'),
          meta: { title: '端口映射', roles: ['admin'] }
        },
        {
          path: 'admin/audit-logs',
          name: 'AdminAuditLogs',
          component: () => import('../views/admin/AdminAuditLogs.vue'),
          meta: { title: '审计日志', roles: ['admin'] }
        },
        {
          path: 'port-mapping/apply',
          name: 'PortMappingApply',
          component: () => import('../views/user/PortMappingApply.vue'),
          meta: { title: '申请映射', roles: ['user'] }
        },
        {
          path: 'my/port-mappings',
          name: 'MyPortMappings',
          component: () => import('../views/user/MyPortMappings.vue'),
          meta: { title: '我的映射', roles: ['user'] }
        }
      ]
    }
  ]
})

router.beforeEach((to, _from, next) => {
  const token = localStorage.getItem('portal_token')
  const user = getStoredUser()

  if (!to.meta.public && !token) {
    next('/login')
    return
  }

  if (to.path === '/login' && token) {
    next(user?.role === 'admin' ? '/dashboard' : '/port-mapping/apply')
    return
  }

  if (to.meta.roles && user && !to.meta.roles.includes(user.role)) {
    next(user.role === 'admin' ? '/dashboard' : '/port-mapping/apply')
    return
  }

  next()
})

export default router
