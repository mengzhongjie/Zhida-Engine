/**
 * 智答引擎（ZhiDa Engine）—— Agent 详情页
 *
 * 4 个 Tab：概览 / 监听中 / 实时消息 / 学习记录
 */
import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Card, Tabs, Descriptions, Tag, Button, Table, Space, Typography, Statistic, Row, Col, message,
} from 'antd'
import {
  ArrowLeftOutlined, PlayCircleOutlined, PauseCircleOutlined,
  ReloadOutlined, CheckCircleOutlined, CloseCircleOutlined,
} from '@ant-design/icons'
import { api } from '../../services/api'

const { Title, Text } = Typography

// 类型定义
interface AgentInfo {
  id: number
  name: string
  description: string
  avatar: string
  is_active: boolean
  status: string
  reply_mode: string
  channel_count: number
  today_messages: number
  today_answers: number
  success_rate: number
}

interface ChannelItem {
  id: number
  chat_name: string
  channel_type: string
  is_listening: boolean
  listen_mode: string
  today_messages: number
  today_answers: number
}

export default function AgentDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [agent, setAgent] = useState<AgentInfo | null>(null)
  const [channels, setChannels] = useState<ChannelItem[]>([])
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState('overview')

  // 加载数据
  const loadData = useCallback(async () => {
    if (!id) return
    try {
      setLoading(true)
      const [agentData, channelData] = await Promise.all([
        api.get<AgentInfo>(`/agents/${id}`),
        api.get<{ items: ChannelItem[] }>(`/channels?agent_id=${id}`),
      ])
      setAgent(agentData)
      setChannels(channelData.items || [])
    } catch (err) {
      console.error('加载失败:', err)
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    loadData()
  }, [loadData])

  // 启动/停止 Agent
  const toggleAgent = async () => {
    if (!agent) return
    try {
      if (agent.status === 'running') {
        await api.post(`/agents/${agent.id}/stop`)
        message.success('已停止')
      } else {
        await api.post(`/agents/${agent.id}/start`)
        message.success('已启动')
      }
      loadData()
    } catch {
      message.error('操作失败')
    }
  }

  // 渠道表格列
  const channelColumns = [
    { title: '名称', dataIndex: 'chat_name', key: 'chat_name' },
    {
      title: '平台', dataIndex: 'channel_type', key: 'channel_type',
      render: (v: string) => <Tag>{v === 'wechat' ? '微信' : 'QQ'}</Tag>,
    },
    {
      title: '状态', dataIndex: 'is_listening', key: 'is_listening',
      render: (v: boolean) => (
        <Tag color={v ? 'green' : 'default'}>{v ? '监听中' : '已停止'}</Tag>
      ),
    },
    {
      title: '监听模式', dataIndex: 'listen_mode', key: 'listen_mode',
      render: (v: string) => {
        const map: Record<string, string> = { all: '全部', mentioned: '仅 @', questions: '仅问题' }
        return map[v] || v
      },
    },
    { title: '今日消息', dataIndex: 'today_messages', key: 'today_messages' },
    { title: '今日回答', dataIndex: 'today_answers', key: 'today_answers' },
  ]

  if (!agent) {
    return <Card loading={loading}>加载中...</Card>
  }

  const statusTag = (status: string) => {
    const config: Record<string, { color: string; text: string }> = {
      running: { color: 'green', text: '运行中' },
      stopped: { color: 'default', text: '已停止' },
    }
    const c = config[status] || { color: 'default', text: status }
    return <Tag color={c.color}>{c.text}</Tag>
  }

  return (
    <div>
      {/* 顶部导航 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>返回</Button>
          <Title level={3} style={{ margin: 0 }}>
            <span style={{ fontSize: 28, marginRight: 8 }}>{agent.avatar || '🤖'}</span>
            {agent.name}
            {statusTag(agent.status)}
          </Title>
        </Space>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={loadData}>刷新</Button>
          <Button
            type={agent.status === 'running' ? 'default' : 'primary'}
            icon={agent.status === 'running' ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
            onClick={toggleAgent}
          >
            {agent.status === 'running' ? '停止' : '启动'}
          </Button>
        </Space>
      </div>

      {/* 统计卡片 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={12} sm={6}>
          <Card><Statistic title="监听渠道" value={agent.channel_count} /></Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card><Statistic title="今日消息" value={agent.today_messages} /></Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card><Statistic title="今日回答" value={agent.today_answers} /></Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card><Statistic title="成功率" value={agent.success_rate} suffix="%" /></Card>
        </Col>
      </Row>

      {/* Tab 内容 */}
      <Card>
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
          {
            key: 'overview',
            label: '概览',
            children: (
              <Descriptions bordered column={2}>
                <Descriptions.Item label="名称">{agent.name}</Descriptions.Item>
                <Descriptions.Item label="状态">{statusTag(agent.status)}</Descriptions.Item>
                <Descriptions.Item label="回复模式">
                  {agent.reply_mode === 'auto' ? '自动回复' : agent.reply_mode === 'manual' ? '手动回复' : '混合模式'}
                </Descriptions.Item>
                <Descriptions.Item label="监听渠道数">{agent.channel_count}</Descriptions.Item>
                <Descriptions.Item label="描述" span={2}>
                  {agent.description || '暂无描述'}
                </Descriptions.Item>
              </Descriptions>
            ),
          },
          {
            key: 'channels',
            label: `监听中 (${channels.length})`,
            children: (
              <Table
                dataSource={channels}
                columns={channelColumns}
                rowKey="id"
                pagination={{ pageSize: 10 }}
                locale={{ emptyText: '暂无监听渠道，请添加' }}
              />
            ),
          },
          {
            key: 'messages',
            label: '实时消息',
            children: (
              <div style={{ textAlign: 'center', padding: 48 }}>
                <Text type="secondary">实时消息功能需要 Agent 运行并连接渠道后可用</Text>
              </div>
            ),
          },
          {
            key: 'learning',
            label: '学习记录',
            children: (
              <div style={{ textAlign: 'center', padding: 48 }}>
                <Text type="secondary">学习记录将显示从聊天中自动提取的问答对</Text>
              </div>
            ),
          },
        ]} />
      </Card>
    </div>
  )
}