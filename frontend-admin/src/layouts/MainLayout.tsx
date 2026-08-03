/**
 * 智答引擎（ZhiDa Engine）—— 主布局
 *
 * 侧边栏导航 + 内容区，暗色主题。
 */
import { useState } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Layout, Menu, Typography, Tag } from 'antd'
import {
  DashboardOutlined,
  ClusterOutlined,
  SettingOutlined,
  BookOutlined,
  TeamOutlined,
} from '@ant-design/icons'
import zhidaLogo from '../assets/zhida-logo.png'

const { Sider, Content } = Layout
const { Text } = Typography

// 导航菜单配置
const menuItems = [
  {
    key: '/',
    icon: <DashboardOutlined />,
    label: '仪表盘',
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
    key: '/settings',
    icon: <SettingOutlined />,
    label: '设置',
  },
  {
    key: '/invitations',
    icon: <TeamOutlined />,
    label: '邀请码',
  },
]

export default function MainLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const [collapsed, setCollapsed] = useState(false)

  // 当前选中的菜单项
  const selectedKey = '/' + location.pathname.split('/')[1]

  return (
    <Layout className="app-shell">
      {/* 侧边栏 */}
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        width={232}
        className="app-sider"
      >
        {/* Logo 区域 */}
        <div className="app-brand">
          <img
            src={zhidaLogo}
            alt="智答引擎"
            title="智答引擎"
            style={{ width: collapsed ? 32 : 38, height: collapsed ? 32 : 38, borderRadius: 10, objectFit: 'cover' }}
          />
          {!collapsed && <Text strong className="app-brand-text">智答引擎</Text>}
        </div>

        {/* 导航菜单 */}
        <Menu
          mode="inline"
          selectedKeys={[selectedKey === '/' ? '/' : selectedKey]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          className="app-menu"
        />

      </Sider>

      {/* 内容区 */}
      <Content className="app-content">
        <header className="app-topbar">
          <div><Text type="secondary">智答引擎 / 管理台</Text></div>
          <Tag color="success">本地服务</Tag>
        </header>
        <Outlet />
      </Content>
    </Layout>
  )
}
