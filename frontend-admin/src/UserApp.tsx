import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { Spin } from 'antd'
import LoginPage from './pages/login'
import UserPage from './pages/user'

function UserGate() {
  const [state, setState] = useState<'loading' | 'ok' | 'denied'>('loading')
  const location = useLocation()

  useEffect(() => {
    fetch('/api/v1/auth/me?role=user', { credentials: 'include' })
      .then(async response => ({ ok: response.ok, data: await response.json() }))
      .then(result => setState(result.ok && result.data.role === 'user' ? 'ok' : 'denied'))
      .catch(() => setState('denied'))
  }, [])

  if (state === 'loading') return <div className="route-loading"><Spin /></div>
  if (state === 'denied') return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <Outlet />
}

/** 用户站只编译用户登录与对话能力，不携带管理后台页面和配置接口。 */
export default function UserApp() {
  return <Routes>
    <Route path="/login" element={<LoginPage fixedRole="user" />} />
    <Route element={<UserGate />}><Route index element={<UserPage />} /></Route>
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes>
}
