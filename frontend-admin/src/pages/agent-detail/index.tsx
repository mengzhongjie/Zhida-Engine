/** Agent 详情：知识库管理与微信小程序公开控制。 */
import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Button, Card, Col, Descriptions, Modal, Popconfirm, Row, Space, Statistic,
  Switch, Table, Tabs, Tag, Typography, message,
} from 'antd'
import {
  ArrowLeftOutlined, DisconnectOutlined, PauseCircleOutlined, PlayCircleOutlined,
  PlusOutlined,
} from '@ant-design/icons'
import { api } from '../../services/api'

const { Title, Text } = Typography

interface AgentInfo {
  id: number
  name: string
  description: string
  avatar: string
  is_active: boolean
  is_public: boolean
  status: string
  reply_mode: string
  today_messages: number
  today_answers: number
  success_rate: number
}

interface KnowledgeBase {
  id: number
  name: string
  description: string
  document_count: number
  chunk_count: number
  agent_id: number | null
  is_active: boolean
}

export default function AgentDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [agent, setAgent] = useState<AgentInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState('overview')
  const [kbList, setKbList] = useState<KnowledgeBase[]>([])
  const [kbLoading, setKbLoading] = useState(false)
  const [mountModalVisible, setMountModalVisible] = useState(false)
  const [availableKbList, setAvailableKbList] = useState<KnowledgeBase[]>([])
  const [selectedKbIds, setSelectedKbIds] = useState<number[]>([])
  const [mountModalLoading, setMountModalLoading] = useState(false)

  const loadAgent = useCallback(async () => {
    if (!id) return
    try {
      setLoading(true)
      setAgent(await api.get<AgentInfo>(`/agents/${id}`))
    } catch (error) {
      console.error('加载 Agent 失败:', error)
      message.error('加载 Agent 失败')
    } finally {
      setLoading(false)
    }
  }, [id])

  const loadKnowledgeBases = useCallback(async () => {
    if (!id) return
    setKbLoading(true)
    try {
      const data = await api.get<{ items: KnowledgeBase[] }>(`/knowledge/bases?agent_id=${id}`)
      setKbList(data.items || [])
    } catch (error) {
      console.error('加载知识库失败:', error)
      setKbList([])
    } finally {
      setKbLoading(false)
    }
  }, [id])

  useEffect(() => { loadAgent() }, [loadAgent])
  useEffect(() => {
    if (activeTab === 'knowledge') loadKnowledgeBases()
  }, [activeTab, loadKnowledgeBases])

  const toggleAgent = async () => {
    if (!agent) return
    try {
      await api.post(`/agents/${agent.id}/${agent.status === 'running' ? 'stop' : 'start'}`)
      message.success(agent.status === 'running' ? '已停止' : '已启动')
      loadAgent()
    } catch {
      message.error('操作失败')
    }
  }

  const updateMiniProgramVisibility = async (isPublic: boolean) => {
    if (!agent) return
    try {
      const updated = await api.put<AgentInfo>(`/agents/${agent.id}`, { is_public: isPublic })
      setAgent(updated)
      message.success(isPublic ? '已在小程序公开' : '已取消小程序公开')
    } catch {
      message.error('更新失败')
    }
  }

  const openMountModal = async () => {
    setMountModalVisible(true)
    setSelectedKbIds([])
    setMountModalLoading(true)
    try {
      const data = await api.get<{ items: KnowledgeBase[] }>('/knowledge/bases/independent')
      setAvailableKbList(data.items || [])
    } catch {
      setAvailableKbList([])
      message.error('加载可挂载知识库失败')
    } finally {
      setMountModalLoading(false)
    }
  }

  const mountKnowledgeBases = async () => {
    if (!id || selectedKbIds.length === 0) {
      message.warning('请选择要挂载的知识库')
      return
    }
    setMountModalLoading(true)
    try {
      await Promise.all(selectedKbIds.map((kbId) => api.post(`/knowledge/bases/${kbId}/attach`, { agent_id: Number(id) })))
      message.success(`已挂载 ${selectedKbIds.length} 个知识库`)
      setMountModalVisible(false)
      loadKnowledgeBases()
    } catch {
      message.error('挂载失败')
    } finally {
      setMountModalLoading(false)
    }
  }

  const unbindKnowledgeBase = async (kbId: number) => {
    try {
      await api.post(`/knowledge/bases/${kbId}/detach`)
      message.success('已解绑知识库')
      loadKnowledgeBases()
    } catch {
      message.error('解绑失败')
    }
  }

  if (loading || !agent) return <Card loading />

  const statusTag = agent.status === 'running'
    ? <Tag color="green">运行中</Tag>
    : <Tag>已停止</Tag>

  const knowledgeColumns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '文档数', dataIndex: 'document_count', key: 'document_count', width: 100 },
    { title: '切片数', dataIndex: 'chunk_count', key: 'chunk_count', width: 100 },
    {
      title: '状态', dataIndex: 'is_active', key: 'is_active', width: 100,
      render: (value: boolean) => <Tag color={value ? 'green' : 'default'}>{value ? '启用' : '停用'}</Tag>,
    },
    {
      title: '操作', key: 'action', width: 120,
      render: (_: unknown, record: KnowledgeBase) => (
        <Popconfirm title="确认解绑该知识库？" onConfirm={() => unbindKnowledgeBase(record.id)}>
          <Button type="link" danger icon={<DisconnectOutlined />}>解绑</Button>
        </Popconfirm>
      ),
    },
  ]

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 20 }}>
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)}>返回</Button>
          <Title level={3} style={{ margin: 0 }}>{agent.avatar || '🤖'} {agent.name}</Title>
          {statusTag}
        </Space>
        <Button type={agent.status === 'running' ? 'default' : 'primary'} icon={agent.status === 'running' ? <PauseCircleOutlined /> : <PlayCircleOutlined />} onClick={toggleAgent}>
          {agent.status === 'running' ? '停止' : '启动'}
        </Button>
      </div>

      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={12} sm={8}><Card><Statistic title="今日消息" value={agent.today_messages} /></Card></Col>
        <Col xs={12} sm={8}><Card><Statistic title="今日回答" value={agent.today_answers} /></Card></Col>
        <Col xs={12} sm={8}><Card><Statistic title="成功率" value={agent.success_rate} suffix="%" /></Card></Col>
      </Row>

      <Card>
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
          {
            key: 'overview', label: '概览', children: (
              <Descriptions bordered column={2}>
                <Descriptions.Item label="名称">{agent.name}</Descriptions.Item>
                <Descriptions.Item label="状态">{statusTag}</Descriptions.Item>
                <Descriptions.Item label="回复模式">{agent.reply_mode === 'auto' ? '自动回复' : agent.reply_mode === 'manual' ? '手动回复' : '混合模式'}</Descriptions.Item>
                <Descriptions.Item label="小程序公开">{agent.is_public ? <Tag color="green">已公开</Tag> : <Tag>未公开</Tag>}</Descriptions.Item>
                <Descriptions.Item label="描述" span={2}>{agent.description || '暂无描述'}</Descriptions.Item>
              </Descriptions>
            ),
          },
          {
            key: 'knowledge', label: '知识库', children: (
              <div>
                <div style={{ marginBottom: 16, textAlign: 'right' }}>
                  <Button type="primary" icon={<PlusOutlined />} onClick={openMountModal}>挂载知识库</Button>
                </div>
                <Table rowKey="id" loading={kbLoading} dataSource={kbList} columns={knowledgeColumns} pagination={{ pageSize: 10 }} locale={{ emptyText: '暂无挂载的知识库' }} />
              </div>
            ),
          },
          {
            key: 'miniapp', label: '微信小程序', children: (
              <Space direction="vertical" size="middle">
                <Text>受邀用户只能看到“启用且公开”的 Agent。邀请码和用户配额在「邀请码」页面管理。</Text>
                <Space>
                  <Switch checked={agent.is_public} onChange={updateMiniProgramVisibility} />
                  <Text>{agent.is_public ? '已在小程序公开' : '暂不在小程序公开'}</Text>
                </Space>
              </Space>
            ),
          },
        ]} />
      </Card>

      <Modal title="挂载知识库" open={mountModalVisible} onOk={mountKnowledgeBases} onCancel={() => setMountModalVisible(false)} confirmLoading={mountModalLoading} okText="确认挂载" cancelText="取消" width={700}>
        <Table rowKey="id" loading={mountModalLoading} dataSource={availableKbList} columns={knowledgeColumns.slice(0, 4)} rowSelection={{ selectedRowKeys: selectedKbIds, onChange: (keys) => setSelectedKbIds(keys.map(Number)) }} pagination={{ pageSize: 6 }} size="small" locale={{ emptyText: '暂无可挂载的知识库' }} />
      </Modal>
    </div>
  )
}
