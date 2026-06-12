import axios from 'axios'
import { useToastStore } from '../stores/toastStore'

const api = axios.create({
  baseURL: '/api',
  timeout: 120_000, // 2 minutes for large file uploads
})

// Request interceptor
api.interceptors.request.use(
  (config) => config,
  (error) => {
    return Promise.reject(error)
  }
)

// Response interceptor — global error handling
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const toast = useToastStore()

    if (error.response) {
      const status = error.response.status
      const detail = error.response.data?.detail || '未知错误'

      if (status === 413) {
        toast.error(`文件过大：${detail}`)
      } else if (status === 400) {
        toast.error(`请求错误：${detail}`)
      } else if (status === 404) {
        toast.error(`未找到：${detail}`)
      } else if (status >= 500) {
        toast.error(`服务器错误：${detail}`)
      } else {
        toast.error(`错误 (${status})：${detail}`)
      }
    } else if (error.request) {
      toast.error('网络错误：无法连接到服务器')
    } else {
      toast.error(`请求配置错误：${error.message}`)
    }

    return Promise.reject(error)
  }
)

export default api
