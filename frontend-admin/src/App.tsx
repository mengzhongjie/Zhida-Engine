/**
 * 智答引擎（ZhiDa Engine）—— 路由配置
 *
 * 使用 HashRouter，所有路由通过 # 后的 hash 管理。
 */
import { Navigate, Routes, Route } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useEffect, useState } from 'react'
import MainLayout from './layouts/MainLayout'
import Dashboard from './pages/dashboard'
import AgentDetail from './pages/agent-detail'
import AgentNew from './pages/agent-new'
import Settings from './pages/settings'
import Knowledge from './pages/knowledge'
import Invitations from './pages/invitations'
import AdminLogin from './pages/admin-login'
import { api } from './services/api'

function AdminGuard({ children }: { children: ReactNode }) {
  const [required, setRequired] = useState<boolean | null>(null)
  useEffect(() => {
    api.get<{ required: boolean }>('/admin/auth/status')
      .then((data) => setRequired(data.required))
      .catch(() => setRequired(true))
  }, [])
  if (required === null) return null
  return required && !localStorage.getItem('zhida_admin_token') ? <Navigate to="/login" replace /> : children
}

function App() {
  return (
    <Routes>
      <Route path="/login" element={<AdminLogin />} />
      <Route path="/" element={<AdminGuard><MainLayout /></AdminGuard>}>
        <Route index element={<Dashboard />} />
        <Route path="agents/:id" element={<AgentDetail />} />
        <Route path="agents/new" element={<AgentNew />} />
        <Route path="settings" element={<Settings />} />
        <Route path="knowledge" element={<Knowledge />} />
        <Route path="invitations" element={<Invitations />} />
      </Route>
    </Routes>
  )
}

export default App
