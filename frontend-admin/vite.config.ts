import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // 构建输出到 backend/static/，由 FastAPI serve 嵌入 .exe
  build: {
    outDir: '../backend/static',
    emptyOutDir: true,
  },
  // 开发服务器代理 API 到后端
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:18900',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://127.0.0.1:18900',
        changeOrigin: true,
      },
    },
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
})
