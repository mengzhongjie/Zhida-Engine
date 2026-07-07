/**
 * 智答引擎（ZhiDa Engine）—— 仪表盘页面
 *
 * 首页：统计卡片 + Agent 列表管理。
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Row, Col, Card, Statistic, Button, Tag, Space, Modal, message, Typography, Progress, Tooltip,
} from 'antd'
import {
  RobotOutlined, MessageOutlined, CheckCircleOutlined, PlusOutlined,
  PlayCircleOutlined, PauseCircleOutlined, DeleteOutlined, EyeOutlined,
  DashboardOutlined, ApiOutlined, ReloadOutlined,
} from '@ant-design/icons'
import { api } from '../../services/api'

const { Title, Text } = Typography

// 类型定义
interface AgentItem {
  id: number
  name: string
  description: string
  avatar: string
  is_active: boolean
  status: string
  channel_count: number
  today_messages: number
  today_answers: number
  success_rate: number
}

interface DashboardStats {
  total_agents: number
  running_agents: number
  total_channels: number
  active_channels: number
  today_messages: number
  today_answers: number
  success_rate: number
  total_knowledge_chunks: number
  total_documents: number
  cache_hit_rate: number
}

// LLM 使用统计
interface LLMUsage {
  id: number
  provider_name: string
  model_name: string
  is_primary: boolean
  is_active: boolean
  tokens_used_today: number
  max_tokens_per_day: number
  requests_today: number
  max_requests_per_minute: number
  max_tokens_per_request: number
  last_test_success: boolean | null
  last_test_at: string | null
}

export default function Dashboard() {
  const navigate = useNavigate()
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [agents, setAgents] = useState<AgentItem[]>([])
  const [llmUsages, setLlmUsages] = useState<LLMUsage[]>([])
  const [loading, setLoading] = useState(true)
  const refreshTimer = useRef<ReturnType<typeof setInterval> | null>(null)

  // 加载仪表盘数据
  const loadData = useCallback(async () => {
    try {
      setLoading(true)
      const [dashboardData, agentData, llmData] = await Promise.all([
        api.get<DashboardStats>('/admin/dashboard'),
        api.get<{ items: AgentItem[] }>('/agents'),
        api.get<LLMUsage[]>('/admin/llm-usage'),
      ])
      setStats(dashboardData)
      setAgents(agentData.items || [])
      setLlmUsages(llmData as any)
    } catch (err) {
      console.error('加载仪表盘数据失败:', err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData()
    // 每 30 秒刷新 LLM 使用统计
    refreshTimer.current = setInterval(loadData, 30000)
    return () => {
      if (refreshTimer.current) clearInterval(refreshTimer.current)
    }
  }, [loadData])

  // 启动/停止 Agent
  const toggleAgent = async (agent: AgentItem) => {
    try {
      if (agent.status === 'running') {
        await api.post(`/agents/${agent.id}/stop`)
        message.success(`已停止 ${agent.name}`)
      } else {
        await api.post(`/agents/${agent.id}/start`)
        message.success(`已启动 ${agent.name}`)
      }
      loadData()
    } catch {
      message.error('操作失败')
    }
  }

  // 删除 Agent
  const deleteAgent = (agent: AgentItem) => {
    Modal.confirm({
      title: '确认删除',
      content: `确定要删除 Agent "${agent.name}" 吗？关联的渠道配置也会被删除。`,
      okText: '删除',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        try {
          await api.delete(`/agents/${agent.id}`)
          message.success('已删除')
          loadData()
        } catch {
          message.error('删除失败')
        }
      },
    })
  }

  // 状态标签
  const statusTag = (status: string) => {
    const config: Record<string, { color: string; text: string }> = {
      running: { color: 'green', text: '运行中' },
      stopped: { color: 'default', text: '已停止' },
      error: { color: 'red', text: '异常' },
    }
    const c = config[status] || { color: 'default', text: status }
    return <Tag color={c.color}>{c.text}</Tag>
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Title level={3} style={{ margin: 0 }}>
          <DashboardOutlined style={{ marginRight: 8 }} />
          仪表盘
        </Title>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/agents/new')}>
          新建 Agent
        </Button>
      </div>

      {/* 统计卡片 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={12} sm={6}>
          <Card hoverable>
            <Statistic
              title="运行中 Agent"
              value={stats?.running_agents || 0}
              suffix={`/ ${stats?.total_agents || 0}`}
              prefix={<RobotOutlined />}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card hoverable>
            <Statistic
              title="今日消息"
              value={stats?.today_messages || 0}
              prefix={<MessageOutlined />}
              valueStyle={{ color: '#1677ff' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card hoverable>
            <Statistic
              title="今日回答"
              value={stats?.today_answers || 0}
              prefix={<CheckCircleOutlined />}
              valueStyle={{ color: '#faad14' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card hoverable>
            <Statistic
              title="响应成功率"
              value={stats?.success_rate || 0}
              suffix="%"
              precision={1}
              valueStyle={{ color: '#1677ff' }}
            />
          </Card>
        </Col>
      </Row>

      {/* LLM 配置监控 —— 每 30s 自动刷新 */}
      {llmUsages.length > 0 && (
        <>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <Title level={4} style={{ margin: 0 }}>
              <ApiOutlined style={{ marginRight: 8 }} />
              LLM 配置监控
            </Title>
            <Tooltip title="每 30 秒自动刷新">
              <Tag color="processing">自动刷新中</Tag>
            </Tooltip>
          </div>
          <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
            {llmUsages.map((usage) => (
              <Col xs={24} sm={12} lg={8} key={usage.id}>
                <Card
                  size="small"
                  title={
                    <Space>
                      {usage.is_primary && <Tag color="blue">主模型</Tag>}
                      {usage.provider_name} / {usage.model_name}
                      {usage.last_test_success === true
                        ? <CheckCircleOutlined style={{ color: '#52c41a' }} />
                        : usage.last_test_success === false
                          ? <Tag color="error">离线</Tag>
                          : null}
                    </Space>
                  }
                >
                  <Row gutter={[8, 12]}>
                    <Col span={12}>
                      <Statistic
                        title="今日 Token"
                        value={usage.tokens_used_today}
                        suffix={`/ ${usage.max_tokens_per_day >= 1000000 ? (usage.max_tokens_per_day / 1000000).toFixed(1) + 'M' : usage.max_tokens_per_day}`}
                        valueStyle={{ fontSize: 18 }}
                      />
                      <Progress
                        percent={usage.max_tokens_per_day > 0
                          ? Math.min(100, Math.round((usage.tokens_used_today / usage.max_tokens_per_day) * 100))
                          : 0}
                        size="small"
                        status={usage.tokens_used_today > usage.max_tokens_per_day * 0.8 ? 'exception' : 'active'}
                        showInfo={false}
                      />
                    </Col>
                    <Col span={12}>
                      <Statistic
                        title="今日请求"
                        value={usage.requests_today}
                        suffix="次"
                        valueStyle={{ fontSize: 18 }}
                      />
                    </Col>
                    <Col span={12}>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        单次上限: {usage.max_tokens_per_request} tokens
                      </Text>
                    </Col>
                    <Col span={12}>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        频率: {usage.max_requests_per_minute} 次/分
                      </Text>
                    </Col>
                  </Row>
                </Card>
              </Col>
            ))}
          </Row>
        </>
      )}

      {/* Agent 列表 */}
      <Title level={4} style={{ marginBottom: 16 }}>Agent 列表</Title>
      <Row gutter={[16, 16]}>
        {agents.map((agent) => (
          <Col xs={24} sm={12} lg={8} key={agent.id}>
            <Card
              hoverable
              loading={loading}
              actions={[
                <EyeOutlined key="view" onClick={() => navigate(`/agents/${agent.id}`)} />,
                agent.status === 'running' ? (
                  <PauseCircleOutlined key="stop" onClick={() => toggleAgent(agent)} />
                ) : (
                  <PlayCircleOutlined key="start" onClick={() => toggleAgent(agent)} />
                ),
                <DeleteOutlined key="delete" onClick={() => deleteAgent(agent)} />,
              ]}
            >
              <Card.Meta
                avatar={
                  <span style={{ fontSize: 32 }}>{agent.avatar || '🤖'}</span>
                }
                title={
                  <Space>
                    <span className={`status-dot ${agent.status}`} />
                    {agent.name}
                    {statusTag(agent.status)}
                  </Space>
                }
                description={
                  <>
                    <Text type="secondary">{agent.description || '暂无描述'}</Text>
                    <div style={{ marginTop: 12 }}>
                      <Row gutter={8}>
                        <Col span={8}>
                          <Text type="secondary" style={{ fontSize: 12 }}>监听</Text>
                          <br />
                          <Text strong>{agent.channel_count} 个</Text>
                        </Col>
                        <Col span={8}>
                          <Text type="secondary" style={{ fontSize: 12 }}>今日回答</Text>
                          <br />
                          <Text strong>{agent.today_answers}</Text>
                        </Col>
                        <Col span={8}>
                          <Text type="secondary" style={{ fontSize: 12 }}>成功率</Text>
                          <br />
                          <Text strong>{agent.success_rate}%</Text>
                        </Col>
                      </Row>
                    </div>
                  </>
                }
              />
            </Card>
          </Col>
        ))}
        {!loading && agents.length === 0 && (
          <Col span={24}>
            <Card style={{ textAlign: 'center', padding: 48 }}>
              <RobotOutlined style={{ fontSize: 48, color: '#8c8c8c', marginBottom: 16 }} />
              <br />
              <Text type="secondary">暂无 Agent，点击上方按钮创建第一个</Text>
            </Card>
          </Col>
        )}
      </Row>
    </div>
  )
}