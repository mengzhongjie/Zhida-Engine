/**
 * 智答引擎（ZhiDa Engine）—— 前端入口
 *
 * 使用 React 18 + Ant Design 5 + HashRouter。
 * 构建产物嵌入 backend/static/，由 FastAPI 直接 serve。
 */
import React from 'react'
import ReactDOM from 'react-dom/client'
import { HashRouter } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#4f46e5',
          borderRadius: 12,
          colorBgContainer: '#ffffff',
          colorBgLayout: '#f7f8fc',
        },
      }}
    >
      <HashRouter>
        <App />
      </HashRouter>
    </ConfigProvider>
  </React.StrictMode>
)
