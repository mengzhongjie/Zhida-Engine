/**
 * 智答引擎（ZhiDa Engine）—— 前端入口
 *
 * 使用 React 18 + Ant Design 5 + HashRouter。
 * 构建产物嵌入 backend/static/，由 FastAPI 直接 serve。
 */
import React from 'react'
import ReactDOM from 'react-dom/client'
import { HashRouter } from 'react-router-dom'
import { ConfigProvider, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: theme.darkAlgorithm,  // 暗色主题
        token: {
          colorPrimary: '#1677ff',
          borderRadius: 8,
          colorBgContainer: '#1a1a2e',
          colorBgLayout: '#0f0f1a',
        },
      }}
    >
      <HashRouter>
        <App />
      </HashRouter>
    </ConfigProvider>
  </React.StrictMode>
)