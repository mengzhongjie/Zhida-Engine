/**
 * 智答引擎（ZhiDa Engine）—— 主布局
 *
 * 侧边栏导航 + 内容区，暗色主题。
 */
import { useState } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Layout, Menu, Typography } from 'antd'
import {
  DashboardOutlined,
  RobotOutlined,
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
    icon: <RobotOutlined />,
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
    <Layout style={{ height: '100vh' }}>
      {/* 侧边栏 */}
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        width={220}
        style={{
          background: 'linear-gradient(180deg, #0a1b32, #07111f)',
          borderRight: '1px solid rgba(119,177,255,0.16)',
        }}
      >
        {/* Logo 区域 */}
        <div style={{
          height: 64,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          borderBottom: '1px solid rgba(119,177,255,0.16)',
        }}>
          <img
            src={zhidaLogo}
            alt="智答引擎"
            title="智答引擎"
            style={{ width: collapsed ? 34 : 42, height: collapsed ? 34 : 42, borderRadius: 10, objectFit: 'cover' }}
          />
          {!collapsed && <Text strong style={{ color: '#fff', fontSize: 20, marginLeft: 10, whiteSpace: 'nowrap' }}>智答引擎</Text>}
        </div>

        {/* 导航菜单 */}
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[selectedKey === '/' ? '/' : selectedKey]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{
            background: 'transparent',
            borderRight: 'none',
            marginTop: 8,
          }}
        />

      </Sider>

      {/* 内容区 */}
      <Content style={{
        overflow: 'auto',
        padding: 24,
        background: 'transparent',
      }}>
        <Outlet />
      </Content>
    </Layout>
  )
}
