/**
 * 智答引擎（ZhiDa Engine）—— Agent 详情页
 *
 * 6 个 Tab：概览 / 知识库 / 监听中 / 渠道配置 / 实时消息 / 学习记录
 */
import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Card, Tabs, Descriptions, Tag, Button, Table, Space, Typography, Statistic, Row, Col, message,
  Modal, Form, Input, Select, Radio, Popconfirm,
} from 'antd'
import {
  ArrowLeftOutlined, PlayCircleOutlined, PauseCircleOutlined,
  ReloadOutlined, PlusOutlined, DisconnectOutlined,
} from '@ant-design/icons'
import { api } from '../../services/api'
import ChannelLoginModal from '../../components/ChannelLoginModal'

const { Title, Text } = Typography

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

interface KnowledgeBase {
  id: number
  name: string
  description: string
  doc_count: number
  chunk_count: number
  agent_id: number | null
  is_active: boolean
}

interface ChannelConfig {
  id: number
  name: string
  platform: string
  chat_id: string
  listen_mode: string
  status: string
}

export default function AgentDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [agent, setAgent] = useState<AgentInfo | null>(null)
  const [channels, setChannels] = useState<ChannelItem[]>([])
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState('overview')

  const [kbList, setKbList] = useState<KnowledgeBase[]>([])
  const [kbLoading, setKbLoading] = useState(false)

  const [channelConfigs, setChannelConfigs] = useState<ChannelConfig[]>([])
  const [channelConfigLoading, setChannelConfigLoading] = useState(false)

  const [mountModalVisible, setMountModalVisible] = useState(false)
  const [availableKbList, setAvailableKbList] = useState<KnowledgeBase[]>([])
  const [selectedKbIds, setSelectedKbIds] = useState<number[]>([])
  const [mountModalLoading, setMountModalLoading] = useState(false)

  const [addChannelModalVisible, setAddChannelModalVisible] = useState(false)
  const [addChannelForm] = Form.useForm()
  const [addChannelLoading, setAddChannelLoading] = useState(false)

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

  const loadKnowledgeBases = useCallback(async () => {
    if (!id) return
    setKbLoading(true)
    try {
      const data = await api.get<{ items: KnowledgeBase[] }>(`/knowledge/bases?agent_id=${id}`)
      setKbList(data.items || [])
    } catch (err) {
      console.error('加载知识库失败:', err)
      setKbList([])
    } finally {
      setKbLoading(false)
    }
  }, [id])

  const loadChannelConfigs = useCallback(async () => {
    if (!id) return
    setChannelConfigLoading(true)
    try {
      const data = await api.get<{ items: ChannelConfig[] }>(`/channel-configs?agent_id=${id}`)
      setChannelConfigs(data.items || [])
    } catch (err) {
      console.error('加载渠道配置失败:', err)
      setChannelConfigs([])
    } finally {
      setChannelConfigLoading(false)
    }
  }, [id])

  useEffect(() => {
    loadData()
  }, [loadData])

  useEffect(() => {
    if (activeTab === 'knowledge') {
      loadKnowledgeBases()
    }
  }, [activeTab, loadKnowledgeBases])

  useEffect(() => {
    if (activeTab === 'channel-config') {
      loadChannelConfigs()
    }
  }, [activeTab, loadChannelConfigs])

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

  const handleUnbindKb = async (kbId: number) => {
    try {
      await api.put(`/knowledge/bases/${kbId}`, { agent_id: null })
      message.success('解绑成功')
      loadKnowledgeBases()
    } catch {
      message.error('解绑失败')
    }
  }

  const openMountModal = async () => {
    setMountModalVisible(true)
    setSelectedKbIds([])
    setMountModalLoading(true)
    try {
      const data = await api.get<{ items: KnowledgeBase[] }>('/knowledge/bases')
      setAvailableKbList((data.items || []).filter((kb) => !kb.agent_id))
    } catch (err) {
      console.error('加载可用知识库失败:', err)
      setAvailableKbList([])
    } finally {
      setMountModalLoading(false)
    }
  }

  const handleMountKb = async () => {
    if (selectedKbIds.length === 0) {
      message.warning('请选择要挂载的知识库')
      return
    }
    setMountModalLoading(true)
    try {
      for (const kbId of selectedKbIds) {
        await api.put(`/knowledge/bases/${kbId}`, { agent_id: Number(id) })
      }
      message.success(`成功挂载 ${selectedKbIds.length} 个知识库`)
      setMountModalVisible(false)
      loadKnowledgeBases()
    } catch {
      message.error('挂载失败')
    } finally {
      setMountModalLoading(false)
    }
  }

  const handleAddChannel = async (data: {
    channel_type: string
    chat_id: string
    chat_name: string
    chat_type: 'group' | 'private'
    target_users?: string[]
  }) => {
    try {
      setAddChannelLoading(true)
      await api.post('/channels', {
        agent_id: Number(id),
        channel_type: data.channel_type,
        chat_id: data.chat_id,
        chat_name: data.chat_name,
        listen_mode: 'all',
        enable_learning: true,
        target_users: data.target_users ? JSON.stringify(data.target_users) : undefined,
        auto_reply: true,
        reply_with_source: true,
        auto_mention_on_fail: true,
      })
      message.success('添加渠道成功')
      setAddChannelModalVisible(false)
      loadChannelConfigs()
      loadData()
    } catch (err: any) {
      if (err?.errorFields) return
      message.error(err.response?.data?.detail || '添加渠道失败')
    } finally {
      setAddChannelLoading(false)
    }
  }

  const handleToggleChannel = async (record: ChannelConfig) => {
    try {
      const newStatus = record.status === 'active' ? 'inactive' : 'active'
      await api.put(`/channel-configs/${record.id}`, { status: newStatus })
      message.success(newStatus === 'active' ? '已启动' : '已停止')
      loadChannelConfigs()
    } catch {
      message.error('操作失败')
    }
  }

  const handleDeleteChannel = async (record: ChannelConfig) => {
    try {
      await api.delete(`/channel-configs/${record.id}`)
      message.success('删除成功')
      loadChannelConfigs()
    } catch {
      message.error('删除失败')
    }
  }

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

  const kbColumns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '文档数', dataIndex: 'doc_count', key: 'doc_count', width: 100 },
    { title: '切片数', dataIndex: 'chunk_count', key: 'chunk_count', width: 100 },
    {
      title: '是否启用',
      dataIndex: 'is_active',
      key: 'is_active',
      width: 100,
      render: (v: boolean) => (
        <Tag color={v ? 'green' : 'default'}>{v ? '启用' : '停用'}</Tag>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_: any, record: KnowledgeBase) => (
        <Popconfirm
          title="确认解绑该知识库？"
          onConfirm={() => handleUnbindKb(record.id)}
          okText="确认"
          cancelText="取消"
        >
          <Button type="link" danger icon={<DisconnectOutlined />}>解绑</Button>
        </Popconfirm>
      ),
    },
  ]

  const availableKbColumns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '文档数', dataIndex: 'doc_count', key: 'doc_count', width: 100 },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      render: (v: string) => v || '-',
    },
  ]

  const availableKbRowSelection = {
    selectedRowKeys: selectedKbIds,
    onChange: (selectedRowKeys: React.Key[]) => {
      setSelectedKbIds(selectedRowKeys.map((k) => Number(k)))
    },
  }

  const channelConfigColumns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    {
      title: '平台',
      dataIndex: 'platform',
      key: 'platform',
      width: 100,
      render: (v: string) => <Tag>{v === 'wechat' ? '微信' : 'QQ'}</Tag>,
    },
    {
      title: '监听模式',
      dataIndex: 'listen_mode',
      key: 'listen_mode',
      width: 120,
      render: (v: string) => {
        const map: Record<string, string> = { all: '全部', mentioned: '仅 @', questions: '仅问题' }
        return map[v] || v
      },
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (v: string) => (
        <Tag color={v === 'active' ? 'green' : 'default'}>
          {v === 'active' ? '运行中' : '已停止'}
        </Tag>
      ),
    },
    {
      title: '操作',
      key: 'action',
      width: 180,
      render: (_: any, record: ChannelConfig) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            icon={record.status === 'active' ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
            onClick={() => handleToggleChannel(record)}
          >
            {record.status === 'active' ? '停止' : '启动'}
          </Button>
          <Popconfirm
            title="确认删除该渠道？"
            onConfirm={() => handleDeleteChannel(record)}
            okText="确认"
            cancelText="取消"
          >
            <Button type="link" danger size="small">删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
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
            key: 'knowledge',
            label: '知识库',
            children: (
              <div>
                <div style={{ marginBottom: 16, textAlign: 'right' }}>
                  <Button type="primary" icon={<PlusOutlined />} onClick={openMountModal}>
                    挂载知识库
                  </Button>
                </div>
                <Table
                  rowKey="id"
                  loading={kbLoading}
                  dataSource={kbList}
                  columns={kbColumns}
                  pagination={{ pageSize: 10 }}
                  locale={{ emptyText: '暂无挂载的知识库' }}
                />
              </div>
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
            key: 'channel-config',
            label: '渠道配置',
            children: (
              <div>
                <div style={{ marginBottom: 16, textAlign: 'right' }}>
                  <Button type="primary" icon={<PlusOutlined />} onClick={() => setAddChannelModalVisible(true)}>
                    添加渠道
                  </Button>
                </div>
                <Table
                  rowKey="id"
                  loading={channelConfigLoading}
                  dataSource={channelConfigs}
                  columns={channelConfigColumns}
                  pagination={{ pageSize: 10 }}
                  locale={{ emptyText: '暂无渠道配置' }}
                />
              </div>
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

      <Modal
        title="挂载知识库"
        open={mountModalVisible}
        onOk={handleMountKb}
        onCancel={() => setMountModalVisible(false)}
        confirmLoading={mountModalLoading}
        okText="确认挂载"
        cancelText="取消"
        width={700}
      >
        <Table
          rowKey="id"
          loading={mountModalLoading}
          dataSource={availableKbList}
          columns={availableKbColumns}
          rowSelection={availableKbRowSelection}
          pagination={{ pageSize: 6 }}
          size="small"
          locale={{ emptyText: '暂无可挂载的知识库' }}
        />
      </Modal>

      <ChannelLoginModal
        open={addChannelModalVisible}
        onCancel={() => setAddChannelModalVisible(false)}
        onConfirm={handleAddChannel}
        confirmLoading={addChannelLoading}
      />
    </div>
  )
}
