/**
 * 智答引擎（ZhiDa Engine）—— API 客户端
 *
 * 基于 axios 封装，baseURL 自动适配开发/生产环境。
 * 开发环境：Vite proxy 代理到 127.0.0.1:18900
 * 生产环境：前后端同域，直接请求 /api/v1
 */
import axios from 'axios'
import type { AxiosInstance, AxiosRequestConfig } from 'axios'

// 创建 axios 实例
const apiClient: AxiosInstance = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// 响应拦截器 —— 统一错误处理
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response) {
      const { status, data } = error.response
      // 限流错误
      if (status === 429) {
        console.warn('请求过于频繁:', data.detail)
      }
      // 服务不可用
      if (status === 503) {
        console.warn('服务暂不可用:', data.detail)
      }
    }
    return Promise.reject(error)
  }
)

apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('zhida_admin_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 便捷方法
export const api = {
  get: <T = any>(url: string, config?: AxiosRequestConfig) =>
    apiClient.get<T>(url, config).then((res) => res.data),

  post: <T = any>(url: string, data?: any, config?: AxiosRequestConfig) =>
    apiClient.post<T>(url, data, config).then((res) => res.data),

  put: <T = any>(url: string, data?: any, config?: AxiosRequestConfig) =>
    apiClient.put<T>(url, data, config).then((res) => res.data),

  delete: <T = any>(url: string, config?: AxiosRequestConfig) =>
    apiClient.delete<T>(url, config).then((res) => res.data),
}

export default apiClient
