/**
 * 智答引擎（ZhiDa Engine）—— 主布局
 *
 * 侧边栏导航 + 内容区，暗色主题。
 */
import { useEffect, useState } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Button, Drawer, Layout, Menu, Typography, Tag } from 'antd'
import {
  DashboardOutlined,
  ClusterOutlined,
  SettingOutlined,
  BookOutlined,
  MessageOutlined,
  MenuOutlined,
  KeyOutlined,
  LogoutOutlined,
} from '@ant-design/icons'
import zhidaLogo from '../assets/zhida-logo.png'

const { Sider, Content } = Layout
const { Text } = Typography
const mobileViewportQuery = '(max-width: 820px), (hover: none) and (pointer: coarse)'

// 导航菜单配置
const menuItems = [
  {
    key: '/',
    icon: <DashboardOutlined />,
    label: '仪表盘',
  },
  {
    key: '/chat',
    icon: <MessageOutlined />,
    label: '对话',
  },
  {
    key: '/agents',
    icon: <ClusterOutlined />,
    label: 'Agent 管理',
  },
  {
    key: '/knowledge',
    icon: <BookOutlined />,
    label: '知识库',
  },
  {
    key: '/access-codes',
    icon: <KeyOutlined />,
    label: '兑换码',
  },
  {
    key: '/settings',
    icon: <SettingOutlined />,
    label: '设置',
  },
]

export default function MainLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const [collapsed, setCollapsed] = useState(false)
  const [mobile, setMobile] = useState(() => window.matchMedia(mobileViewportQuery).matches)
  const [mobileOpen, setMobileOpen] = useState(false)

  const logout = async () => {
    await fetch('/api/v1/auth/logout', { method: 'POST', credentials: 'include' }).catch(() => undefined)
    navigate('/login', { replace: true })
  }

  useEffect(() => {
    const query = window.matchMedia(mobileViewportQuery)
    const update = () => setMobile(query.matches)
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])

  // 当前选中的菜单项
  const selectedKey = '/' + location.pathname.split('/')[1]
  const navigation = (isCollapsed = false) => <>
    <div className="app-brand">
      <img src={zhidaLogo} alt="智答引擎" title="智答引擎" style={{ width: isCollapsed ? 32 : 38, height: isCollapsed ? 32 : 38, borderRadius: 10, objectFit: 'cover' }} />
      {!isCollapsed && <Text strong className="app-brand-text">智答引擎</Text>}
    </div>
    <Menu mode="inline" selectedKeys={[selectedKey === '/' ? '/' : selectedKey]} items={menuItems} onClick={({ key }) => { navigate(key); setMobileOpen(false) }} className="app-menu" />
  </>

  return (
    <Layout className="app-shell">
      {!mobile && <Sider collapsible collapsed={collapsed} onCollapse={setCollapsed} width={232} className="app-sider">{navigation(collapsed)}</Sider>}
      {mobile && <Drawer className="mobile-nav-drawer" placement="left" width={248} open={mobileOpen} onClose={() => setMobileOpen(false)} closable={false} styles={{ body: { padding: 0 } }}>{navigation()}</Drawer>}

      {/* 内容区 */}
      <Content className="app-content">
        <header className="app-topbar">
          <div className="app-topbar-title">{mobile && <Button className="mobile-menu-trigger" type="text" icon={<MenuOutlined />} onClick={() => setMobileOpen(true)} />}<Text type="secondary">智答引擎 / 管理台</Text></div>
          <div className="app-topbar-actions"><Tag color="success">本地服务</Tag><Button size="small" icon={<LogoutOutlined />} onClick={() => void logout()}>退出</Button></div>
        </header>
        <Outlet />
      </Content>
    </Layout>
  )
}
