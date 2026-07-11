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
  PlusOutlined,
  TeamOutlined,
} from '@ant-design/icons'

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
          background: '#141428',
          borderRight: '1px solid rgba(255,255,255,0.06)',
        }}
      >
        {/* Logo 区域 */}
        <div style={{
          height: 64,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          borderBottom: '1px solid rgba(255,255,255,0.06)',
        }}>
          <Text strong style={{
            color: '#1677ff',
            fontSize: collapsed ? 16 : 20,
            whiteSpace: 'nowrap',
          }}>
            {collapsed ? '智' : '🤖 智答引擎'}
          </Text>
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

        {/* 底部新建按钮 */}
        <div style={{ padding: '12px 16px' }}>
          <Menu
            theme="dark"
            mode="inline"
            selectable={false}
            items={[{
              key: '/agents/new',
              icon: <PlusOutlined />,
              label: collapsed ? '' : '新建 Agent',
            }]}
            onClick={({ key }) => navigate(key)}
            style={{ background: 'transparent', borderRight: 'none' }}
          />
        </div>
      </Sider>

      {/* 内容区 */}
      <Content style={{
        overflow: 'auto',
        padding: 24,
        background: '#0f0f1a',
      }}>
        <Outlet />
      </Content>
    </Layout>
  )
}
