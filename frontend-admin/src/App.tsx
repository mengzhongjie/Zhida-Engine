/**
 * 智答引擎（ZhiDa Engine）—— 路由配置
 *
 * 使用 HashRouter，所有路由通过 # 后的 hash 管理。
 */
import { Routes, Route } from 'react-router-dom'
import MainLayout from './layouts/MainLayout'
import Dashboard from './pages/dashboard'
import AgentDetail from './pages/agent-detail'
import AgentNew from './pages/agent-new'
import AgentList from './pages/agents'
import KnowledgeDetail from './pages/knowledge/detail'
import Settings from './pages/settings'
import Knowledge from './pages/knowledge'
import Invitations from './pages/invitations'

function App() {
  return (
    <Routes>
      <Route path="/" element={<MainLayout />}>
        <Route index element={<Dashboard />} />
        <Route path="agents" element={<AgentList />} />
        <Route path="agents/:id" element={<AgentDetail />} />
        <Route path="agents/new" element={<AgentNew />} />
        <Route path="settings" element={<Settings />} />
        <Route path="knowledge" element={<Knowledge />} />
        <Route path="knowledge/:id" element={<KnowledgeDetail />} />
        <Route path="invitations" element={<Invitations />} />
      </Route>
    </Routes>
  )
}

export default App
