/**
 * 智答引擎（ZhiDa Engine）—— 仪表盘页面
 *
 * 首页：统计卡片 + Agent 列表管理。
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Row, Col, Card, Statistic, Button, Tag, Space, Modal, message, Typography, Progress, Tooltip, DatePicker,
} from 'antd'
import {
  RobotOutlined, MessageOutlined, CheckCircleOutlined,
  PlayCircleOutlined, PauseCircleOutlined, DeleteOutlined, EyeOutlined,
  DashboardOutlined, ApiOutlined,
} from '@ant-design/icons'
import { api } from '../../services/api'
import zhidaLogo from '../../assets/zhida-logo.png'
import dayjs from 'dayjs'
import './index.css'

const { Title, Text } = Typography

// 类型定义
interface AgentItem {
  id: number
  name: string
  description: string
  avatar: string
  is_active: boolean
  is_public: boolean
  status: string
  today_messages: number
  today_answers: number
  success_rate: number
}

interface DashboardStats {
  total_agents: number
  running_agents: number
  today_messages: number
  today_answers: number
  success_rate: number
  total_knowledge_chunks: number
  total_documents: number
  cache_hit_rate: number
}
interface ModelHealth { chat_models: { name: string; role: string; available: boolean; message: string }[]; embedding: { name: string; available: boolean } }
interface ComponentHealth { items: { key: string; name: string; available: boolean; configured?: boolean; message: string }[]; checked_at: string }

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
  const [modelHealth, setModelHealth] = useState<ModelHealth | null>(null)
  const [componentHealth, setComponentHealth] = useState<ComponentHealth | null>(null)
  const [dateRange, setDateRange] = useState<any>([dayjs(), dayjs()])
  const [loading, setLoading] = useState(true)
  const refreshTimer = useRef<ReturnType<typeof setInterval> | null>(null)

  // 加载仪表盘数据
  const loadData = useCallback(async () => {
    try {
      setLoading(true)
      const params = dateRange?.[0] ? `?start_date=${dateRange[0].format('YYYY-MM-DD')}&end_date=${dateRange[1].format('YYYY-MM-DD')}` : ''
      const [dashboardData, agentData, llmData, healthData, components] = await Promise.all([
        api.get<DashboardStats>(`/admin/dashboard${params}`),
        api.get<{ items: AgentItem[] }>('/agents'),
        api.get<LLMUsage[]>('/admin/llm-usage'),
        api.get<ModelHealth>('/admin/model-health'),
        api.get<ComponentHealth>('/admin/component-health'),
      ])
      setStats(dashboardData)
      setAgents(agentData.items || [])
      setLlmUsages(llmData as any)
      setModelHealth(healthData)
      setComponentHealth(components)
    } catch (err) {
      console.error('加载仪表盘数据失败:', err)
    } finally {
      setLoading(false)
    }
  }, [dateRange])

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
      content: `确定要删除 Agent "${agent.name}" 吗？关联的知识库会自动解绑变为独立知识库，不会丢失。`,
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
    <div className="dashboard-page">
      <section className="dashboard-hero">
        <div>
          <Text className="dashboard-kicker">WORKSPACE OVERVIEW</Text>
          <Title level={2} className="dashboard-title"><DashboardOutlined /> 智答概览</Title>
          <Text type="secondary">查看 Agent、知识库与今日问答的运行情况。</Text>
        </div>
        <Space wrap><DatePicker.RangePicker value={dateRange} onChange={(value) => setDateRange(value)} /><Button type="primary" icon={<RobotOutlined />} onClick={() => navigate('/agents')}>管理 Agent</Button></Space>
      </section>

      <section className="dashboard-summary">
        <div><span>知识库文档</span><strong>{stats?.total_documents || 0}</strong><small>份已管理资料</small></div>
        <div><span>知识切片</span><strong>{stats?.total_knowledge_chunks || 0}</strong><small>条可检索内容</small></div>
        <div><span>缓存命中率</span><strong>{stats?.cache_hit_rate || 0}%</strong><small>减少重复调用</small></div>
      </section>

      {/* 统计卡片 */}
      <Row gutter={[16, 16]} className="dashboard-metrics">
        <Col xs={12} sm={6}>
          <Card hoverable className="metric-card metric-green">
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
          <Card hoverable className="metric-card metric-blue">
            <Statistic
              title="今日消息"
              value={stats?.today_messages || 0}
              prefix={<MessageOutlined />}
              valueStyle={{ color: '#1677ff' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card hoverable className="metric-card metric-amber">
            <Statistic
              title="今日回答"
              value={stats?.today_answers || 0}
              prefix={<CheckCircleOutlined />}
              valueStyle={{ color: '#faad14' }}
            />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card hoverable className="metric-card metric-purple">
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

      <Row gutter={[16, 16]} className="dashboard-health">
        <Col xs={24} sm={15}><Card title="问答模型"><Space direction="vertical" size={12}>{modelHealth?.chat_models?.length ? modelHealth.chat_models.map((model) => <div className="model-line" key={`${model.role}-${model.name}`}><Tag color={model.available ? 'success' : 'error'}>{model.available ? '可用' : '不可用'}</Tag><Text type="secondary">{model.role}</Text><Text strong>{model.name}</Text></div>) : <Text type="secondary">未配置</Text>}</Space></Card></Col>
        <Col xs={24} sm={9}><Card title="当前向量化模型"><div className="embedding-health"><Tag color={modelHealth?.embedding.available ? 'success' : 'error'}>{modelHealth?.embedding.available ? '可用' : '不可用'}</Tag><Text strong>{modelHealth?.embedding.name || '检测中'}</Text></div></Card></Col>
      </Row>
      <Card title="组件可用性" extra={<Text type="secondary">每 30 秒检查一次</Text>} style={{ marginBottom: 28 }}>
        <Row gutter={[12, 12]}>{componentHealth?.items?.map(item => <Col xs={24} sm={12} lg={6} key={item.key}><div className="component-health-line"><Tag color={item.available ? 'success' : item.configured === false ? 'default' : 'error'}>{item.available ? '可用' : item.configured === false ? '未配置' : '异常'}</Tag><div><Text strong>{item.name}</Text><br /><Text type="secondary">{item.message}</Text></div></div></Col>) || <Col><Text type="secondary">检测中</Text></Col>}</Row>
      </Card>

      {/* LLM 配置监控 —— 每 30s 自动刷新 */}
      {false && llmUsages.length > 0 && (
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
      <div className="dashboard-section-title"><div><Title level={4}>Agent</Title><Text type="secondary">已接入的知识问答实例</Text></div><Text type="secondary">{agents.length} 个实例</Text></div>
      <Row gutter={[16, 16]}>
        {agents.map((agent) => (
          <Col xs={24} sm={12} lg={8} key={agent.id}>
            <Card
              hoverable
              className="agent-overview-card"
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
                  <img src={zhidaLogo} alt="智答引擎" style={{ width: 40, height: 40, borderRadius: 10, objectFit: 'cover' }} />
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
                          <Text type="secondary" style={{ fontSize: 12 }}>小程序</Text>
                          <br />
                          <Text strong>{agent.is_public ? '公开' : '未公开'}</Text>
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
