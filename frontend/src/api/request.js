import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '../router'

const request = axios.create({
  baseURL: '/api',
  timeout: 20000
})

request.interceptors.request.use((config) => {
  const token = localStorage.getItem('portal_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

request.interceptors.response.use(
  (response) => response.data,
  (error) => {
    const silent = error.config?.silent === true
    const status = error.response?.status
    const message = error.response?.data?.detail || error.message || '请求失败'

    if (status === 401) {
      localStorage.removeItem('portal_token')
      localStorage.removeItem('portal_user')
      if (router.currentRoute.value.path !== '/login') {
        router.push('/login')
      }
    }

    if (!silent && status !== 404) {
      ElMessage.error(typeof message === 'string' ? message : '请求失败')
    }
    return Promise.reject(error)
  }
)

export default request
