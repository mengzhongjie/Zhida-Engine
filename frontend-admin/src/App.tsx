/**
 * 智答引擎（ZhiDa Engine）—— 路由配置
 *
 * 使用 HashRouter，所有路由通过 # 后的 hash 管理。
 */
import { Routes, Route, Navigate, Outlet, useLocation } from 'react-router-dom'
import { useEffect, useState } from 'react'
import MainLayout from './layouts/MainLayout'
import Dashboard from './pages/dashboard'
import AgentDetail from './pages/agent-detail'
import AgentNew from './pages/agent-new'
import AgentList from './pages/agents'
import KnowledgeDetail from './pages/knowledge/detail'
import Settings from './pages/settings'
import SettingsOverview from './pages/settings/overview'
import FeishuSettings from './pages/settings/feishu'
import ReliabilitySettings from './pages/settings/reliability'
import VisionSettings from './pages/settings/vision'
import EmbeddingSettings from './pages/settings/embedding'
import Knowledge from './pages/knowledge'
import Chat from './pages/chat'
import LoginPage from './pages/login'
import UserPage from './pages/user'
import AccessCodes from './pages/access-codes'
import Evaluations from './pages/evaluations'
import { Spin } from 'antd'

function RoleGate({ role }: { role: 'admin' | 'user' }) {
  const [state, setState] = useState<'loading' | 'ok' | 'denied'>('loading')
  const location = useLocation()
  useEffect(() => { fetch(`/api/v1/auth/me?role=${role}`, { credentials: 'include' }).then(async response => ({ ok: response.ok, data: await response.json() })).then(result => setState(result.ok && result.data.role === role ? 'ok' : 'denied')).catch(() => setState('denied')) }, [role])
  if (state === 'loading') return <div className="route-loading"><Spin /></div>
  if (state === 'denied') return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <Outlet />
}

function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage fixedRole="admin" />} />
      <Route element={<RoleGate role="user" />}><Route path="/user" element={<UserPage />} /></Route>
      <Route element={<RoleGate role="admin" />}><Route path="/" element={<MainLayout />}>
        <Route index element={<Dashboard />} />
        <Route path="chat" element={<Chat />} />
        <Route path="evaluations" element={<Evaluations />} />
        <Route path="agents" element={<AgentList />} />
        <Route path="agents/:id" element={<AgentDetail />} />
        <Route path="agents/new" element={<AgentNew />} />
        <Route path="settings" element={<SettingsOverview />} />
        <Route path="settings/sources" element={<FeishuSettings />} />
        <Route path="settings/system" element={<ReliabilitySettings />} />
        <Route path="settings/vision" element={<VisionSettings />} />
        <Route path="settings/embedding" element={<EmbeddingSettings />} />
        <Route path="settings/:section/:provider" element={<Settings />} />
        <Route path="settings/:section" element={<Settings />} />
        <Route path="knowledge" element={<Knowledge />} />
        <Route path="knowledge/:id" element={<KnowledgeDetail />} />
        <Route path="access-codes" element={<AccessCodes />} />
      </Route></Route>
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  )
}

export default App
