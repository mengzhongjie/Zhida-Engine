import { useEffect, useState } from 'react'
import { Button, Card, Space, Tag, Typography, message } from 'antd'
import { ArrowLeftOutlined, MessageOutlined, QqOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api } from '@/services/api'

type ChannelConfig = { enabled: boolean; app_id: string; last_test_success: boolean | null; last_error: string | null }

function ChannelCard(props: { icon: React.ReactNode; title: string; desc: string; config?: ChannelConfig; path: string; testing: boolean; onTest: () => void; onToggle: () => void; nav: (p: string) => void }) {
  const { icon, title, desc, config, path, testing, onTest, onToggle, nav } = props
  const health = config?.last_test_success === true ? '可用' : config?.last_test_success === false ? '不可用' : '待检测'
  return <Card className={`web-search-provider-card ${config?.enabled ? 'is-active' : ''}`}>
    <div className="web-search-provider-main">
      <div><Space size={8}>{icon}<Typography.Text strong>{title}</Typography.Text></Space>
        <Typography.Paragraph type="secondary" style={{ margin: '6px 0 0' }}>{desc}</Typography.Paragraph></div>
      <div className="web-search-provider-status"><Tag className={config?.enabled ? 'search-chain-active' : undefined} color={config?.enabled ? 'success' : 'default'}>{config?.enabled ? '已启用' : '未启用'}</Tag>
        <Typography.Text type={config?.last_test_success === false ? 'danger' : 'secondary'}>{health}</Typography.Text></div>
    </div>
    <Typography.Text className="web-search-health-copy" type="secondary">{config?.last_error || (config?.enabled ? '已启用连接' : '完成凭据配置后即可启用')}</Typography.Text>
    <Space wrap className="web-search-provider-actions">
      <Button onClick={onTest} loading={testing}>测试凭据</Button>
      <Button onClick={() => nav(path)}>配置</Button>
      <Button type={config?.enabled ? 'default' : 'primary'} onClick={onToggle}>{config?.enabled ? '停用' : '启用'}</Button>
    </Space>
  </Card>
}

export default function BotSettings() {
  const navigate = useNavigate()
  const [qq, setQq] = useState<ChannelConfig>()
  const [feishu, setFeishu] = useState<ChannelConfig>()
  const [testing, setTesting] = useState('')

  const load = async () => {
    try {
      const [q, f] = await Promise.all([api.get<ChannelConfig>('/qq-bot/config'), api.get<ChannelConfig>('/feishu-bot/config')])
      setQq(q); setFeishu(f)
    } catch { message.error('加载机器人配置失败') }
  }
  useEffect(() => { void load() }, [])

  const test = async (channel: string, key: string) => {
    setTesting(channel)
    try { const result = await api.post<{ success: boolean; message: string }>(`/${key}/config/test`); result.success ? message.success(result.message) : message.error(result.message); await load() }
    catch (error: any) { message.error(error?.response?.data?.detail || '测试失败') }
    finally { setTesting('') }
  }
  const toggle = async (key: string, enabled: boolean | undefined, app_id: string | undefined) => {
    try { await api.put(`/${key}/config`, { enabled: !enabled, app_id: app_id || '' }); await load(); message.success(enabled ? '机器人已停用' : '机器人已启用') }
    catch (error: any) { message.error(error?.response?.data?.detail || '更新失败') }
  }

  return <div>
    <div className="page-header"><div><Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/settings')} style={{ marginLeft: -8 }}>返回设置</Button><Typography.Title level={3}>机器人</Typography.Title><Typography.Text type="secondary">统一管理外部消息平台；每个平台独立配置凭据和 Agent 绑定。</Typography.Text></div></div>
    <div className="web-search-provider-list">
      <ChannelCard icon={<QqOutlined style={{ color: '#1677ff' }} />} title="QQ 官方机器人" desc="群内 @机器人 后由绑定 Agent 回答" config={qq} path="/settings/bots/qq" testing={testing === 'qq'} onTest={() => test('qq', 'qq-bot')} onToggle={() => toggle('qq-bot', qq?.enabled, qq?.app_id)} nav={navigate} />
      <ChannelCard icon={<MessageOutlined style={{ color: '#1677ff' }} />} title="飞书机器人" desc="飞书群内 @机器人 后由绑定 Agent 回答" config={feishu} path="/settings/bots/feishu" testing={testing === 'feishu'} onTest={() => test('feishu', 'feishu-bot')} onToggle={() => toggle('feishu-bot', feishu?.enabled, feishu?.app_id)} nav={navigate} />
    </div>
  </div>
}
