import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const target = mode === 'user' ? 'user' : 'admin'
  const apiProxy = {
    '/api': {
      target: 'http://127.0.0.1:18900',
      changeOrigin: true,
    },
    '/health': {
      target: 'http://127.0.0.1:18900',
      changeOrigin: true,
    },
  }
  return {
  plugins: [react()],
  define: {
    'import.meta.env.VITE_APP_TARGET': JSON.stringify(target),
  },
  // 两个站点分别构建。生产环境由反向代理以不同主机名提供，避免用户端
  // 下载管理台代码，也让两种 Cookie 保持 host-only 隔离。
  base: './',
  build: {
    outDir: `../backend/static-${target}`,
    emptyOutDir: true,
  },
  // 开发服务器代理 API 到后端
  server: {
    port: 5173,
    // 仅开发调试：允许 cpolar 转发的随机子域名访问本机前端。
    // 正式部署不经过 Vite，而是使用受信 HTTPS 域名提供静态文件。
    allowedHosts: ['.cpolar.top', '.cpolar.cn'],
    proxy: apiProxy,
  },
  // 手机经 cpolar 调试时用预览服务器：它提供已打包的少量静态文件，
  // 不会像 dev server 一样在隧道中逐个传输大量源码模块。
  preview: {
    port: target === 'user' ? 5174 : 5173,
    allowedHosts: ['.cpolar.top', '.cpolar.cn'],
    proxy: apiProxy,
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  }
})
