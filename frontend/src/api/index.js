import request from './request'

export function login(data) {
  return request.post('/login', data)
}

export function logout() {
  return request.post('/logout')
}

export function getPortalConfig() {
  return request.get('/config')
}

export function getDashboardSummary() {
  return request.get('/admin/dashboard/summary')
}

export function getAdminDevices() {
  return request.get('/admin/devices')
}

export function getAdminUsers() {
  return request.get('/admin/users')
}

export function createUser(data) {
  return request.post('/admin/users', data)
}

export function updateUser(id, data) {
  return request.put(`/admin/users/${id}`, data)
}

export function deleteUser(id) {
  return request.delete(`/admin/users/${id}`)
}

export function resetUserPassword(id, password) {
  return request.post(`/admin/users/${id}/reset-password`, { password })
}

export function getAuditLogs(params) {
  return request.get('/admin/audit-logs', { params })
}

export function getAuditLogActions() {
  return request.get('/admin/audit-logs/actions')
}

export function cleanupAuditLogs(data) {
  return request.post('/admin/audit-logs/cleanup', data)
}

export function searchMappingClients(keyword) {
  return request.get('/my/clients/search', { params: { keyword } })
}

export function getMyPortMappings(params) {
  return request.get('/my/port-mappings', { params })
}

export function createPortMapping(data) {
  return request.post('/my/port-mappings', data, { timeout: 60000 })
}

export function releasePortMapping(id) {
  return request.delete(`/my/port-mappings/${id}`)
}

export function getAdminPortMappings(params) {
  return request.get('/admin/port-mappings', { params })
}

export function releaseAdminPortMapping(id) {
  return request.delete(`/admin/port-mappings/${id}`)
}

export function getStoredUser() {
  try {
    const raw = localStorage.getItem('portal_user')
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function setStoredUser(user) {
  if (user) {
    localStorage.setItem('portal_user', JSON.stringify(user))
  } else {
    localStorage.removeItem('portal_user')
  }
}

export function clearAuth() {
  localStorage.removeItem('portal_token')
  localStorage.removeItem('portal_user')
}
