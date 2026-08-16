import { useEffect, useState } from 'react'
import { Button, Card, Space, Tag, Typography, message } from 'antd'
import { ReloadOutlined, DesktopOutlined, QqOutlined, MessageOutlined, QuestionOutlined, ArrowRightOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api } from '@/services/api'

type ChannelStat = { total: number; today: number; last_at: string | null }

const CHANNEL_META: Record<string, { label: string; desc: string; icon: React.ReactNode; color: string; tagColor: string }> = {
  web: { label: '管理台', desc: '管理台对话问答', icon: <DesktopOutlined />, color: '#1677ff', tagColor: 'blue' },
  qq: { label: 'QQ 机器人', desc: '绑定 QQ 群内 @机器人 问答', icon: <QqOutlined />, color: '#22c55e', tagColor: 'green' },
  feishu: { label: '飞书机器人', desc: '绑定飞书群内 @机器人 问答', icon: <MessageOutlined />, color: '#8b5cf6', tagColor: 'purple' },
  unknown: { label: '其他', desc: '未标注渠道的历史记录', icon: <QuestionOutlined />, color: '#94a3b8', tagColor: 'default' },
}

export default function ObservabilityPage() {
  const navigate = useNavigate()
  const [stats, setStats] = useState<{ total: number; channels: Record<string, ChannelStat> }>({ total: 0, channels: {} })
  const [loading, setLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    try { setStats(await api.get<{ total: number; channels: Record<string, ChannelStat> }>('/qa/history/stats')) }
    catch { message.error('加载观测统计失败') }
    finally { setLoading(false) }
  }
  useEffect(() => { void load() }, [])

  const channels = Object.keys(stats.channels).length
    ? Object.keys(stats.channels)
        .filter(ch => CHANNEL_META[ch])
        .map(ch => ({ key: ch, ...CHANNEL_META[ch], stat: stats.channels[ch] }))
    : Object.keys(CHANNEL_META).map(ch => ({ key: ch, ...CHANNEL_META[ch], stat: { total: 0, today: 0, last_at: null } }))

  return (
    <div className="observe-page">
      <div className="page-header">
        <div>
          <Typography.Title level={3} style={{ margin: 0 }}>问答观测</Typography.Title>
          <Typography.Text type="secondary">全渠道问答链路观测，共 {stats.total} 条记录。进入渠道查看详情问答。</Typography.Text>
        </div>
        <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>刷新</Button>
      </div>

      <div className="web-search-provider-list" style={{ marginTop: 18 }}>
        {channels.map(ch => (
          <Card key={ch.key} size="small" className={`web-search-provider-card ${ch.stat.total > 0 ? 'is-active' : ''}`}>
            <div className="web-search-provider-main">
              <div>
                <Space size={8}>
                  <span style={{ color: ch.color, fontSize: 17 }}>{ch.icon}</span>
                  <Typography.Text strong>{ch.label}</Typography.Text>
                  <Tag color={ch.tagColor}>今日 {ch.stat.today}</Tag>
                </Space>
                <Typography.Text type="secondary">{ch.desc}</Typography.Text>
              </div>
              <div className="web-search-provider-status">
                <Tag className={ch.stat.total > 0 ? 'search-chain-active' : undefined} color={ch.stat.total > 0 ? 'success' : 'default'}>
                  {ch.stat.total > 0 ? '有数据' : '无记录'}
                </Tag>
                <Typography.Text type="secondary">共 {ch.stat.total} 条</Typography.Text>
              </div>
            </div>
            <Typography.Text className="web-search-health-copy" type="secondary">
              {ch.stat.last_at ? `最近问答：${ch.stat.last_at}` : (ch.stat.total > 0 ? '' : '暂无问答记录，渠道接入后自动统计')}
            </Typography.Text>
            <Space wrap className="web-search-provider-actions">
              <Button type="primary" icon={<ArrowRightOutlined />} onClick={() => navigate(`/observability/${ch.key}`)}>查看问答</Button>
            </Space>
          </Card>
        ))}
      </div>
    </div>
  )
}
