/** Agent 详情：知识库管理与运行控制。 */
import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Button, Card, Col, Descriptions, Modal, Popconfirm, Row, Space, Statistic,
  Form, Input, InputNumber, Table, Tabs, Tag, Typography, message,
} from 'antd'
import {
  ArrowLeftOutlined, DisconnectOutlined, PauseCircleOutlined, PlayCircleOutlined,
  EditOutlined, PlusOutlined,
} from '@ant-design/icons'
import { api } from '../../services/api'
import PersonaPicker, { defaultPersonaPresets } from '../../components/PersonaPicker'
import type { PersonaPreset } from '../../components/PersonaPicker'
import zhidaLogo from '../../assets/zhida-logo.png'

const { Title } = Typography

interface AgentInfo {
  id: number
  name: string
  description: string
  avatar: string
  is_active: boolean
  status: string
  today_messages: number
  today_answers: number
  success_rate: number
  persona_preset: 'professional' | 'tutor' | 'friendly' | 'direct' | 'custom'
  persona_custom_instruction?: string
  context_window_k: number
  concise_top_k: number
  detailed_top_k: number
  concise_rewrite_count: number
  detailed_rewrite_count: number
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
  const [editingName, setEditingName] = useState(false); const [nameForm] = Form.useForm()
  const [personaPresets, setPersonaPresets] = useState<PersonaPreset[]>(defaultPersonaPresets)

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
  useEffect(() => { api.get<PersonaPreset[]>('/admin/persona-presets').then(setPersonaPresets).catch(() => undefined) }, [])
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

  const saveName = async () => {
    if (!agent) return
    const values = await nameForm.validateFields()
    const selectedPreset = personaPresets.find(item => item.key === values.persona_preset)
    if (selectedPreset) await api.put(`/admin/persona-presets/${selectedPreset.key}`, { name: selectedPreset.name, instruction: selectedPreset.instruction })
    const updated = await api.put<AgentInfo>(`/agents/${agent.id}`, values)
    setAgent(updated); setEditingName(false); message.success('Agent 信息与回答人格已更新')
  }

  const openMountModal = async () => {
    setMountModalVisible(true)
    setSelectedKbIds([])
    setMountModalLoading(true)
    try {
      const data = await api.get<{ items: KnowledgeBase[] }>('/knowledge/bases')
      setAvailableKbList((data.items || []).filter(item => !kbList.some(mounted => mounted.id === item.id)))
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
      await api.post(`/knowledge/bases/${kbId}/detach?agent_id=${id}`)
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
    <div className="content-page">
      <div className="page-header">
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={() => navigate(-1)}>返回</Button>
          <img src={zhidaLogo} alt="智答引擎" style={{ width: 36, height: 36, borderRadius: 9, objectFit: 'cover' }} />
          <Title level={3} style={{ margin: 0 }}>{agent.name}</Title>
          {statusTag}
        </Space>
        <Button type={agent.status === 'running' ? 'default' : 'primary'} icon={agent.status === 'running' ? <PauseCircleOutlined /> : <PlayCircleOutlined />} onClick={toggleAgent}>
          {agent.status === 'running' ? '停止' : '启动'}
        </Button>
      </div>

      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={8} sm={8}><Card><Statistic title="今日消息" value={agent.today_messages} /></Card></Col>
        <Col xs={8} sm={8}><Card><Statistic title="今日回答" value={agent.today_answers} /></Card></Col>
        <Col xs={8} sm={8}><Card><Statistic title="成功率" value={agent.success_rate} suffix="%" /></Card></Col>
      </Row>

      <Card>
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
          {
            key: 'overview', label: '概览', children: (
              <Card size="small" title="Agent 概览" extra={<Button icon={<EditOutlined />} onClick={() => { nameForm.setFieldsValue({ name: agent.name, description: agent.description, persona_preset: agent.persona_preset, persona_custom_instruction: agent.persona_custom_instruction, context_window_k: agent.context_window_k || 64, concise_top_k: agent.concise_top_k || 4, detailed_top_k: agent.detailed_top_k || 8, concise_rewrite_count: agent.concise_rewrite_count ?? 3, detailed_rewrite_count: agent.detailed_rewrite_count ?? 3 }); setEditingName(true) }}>编辑</Button>}><Descriptions className="agent-overview-descriptions" bordered column={2}>
                <Descriptions.Item label="名称">{agent.name}</Descriptions.Item>
                <Descriptions.Item label="状态">{statusTag}</Descriptions.Item>
                <Descriptions.Item label="回复方式">AI 回复</Descriptions.Item>
                <Descriptions.Item label="回答人格">{agent.persona_preset === 'custom' ? '自定义人格' : personaPresets.find(item => item.key === agent.persona_preset)?.name}</Descriptions.Item>
                <Descriptions.Item label="上下文窗口">{agent.context_window_k || 64}K</Descriptions.Item>
                <Descriptions.Item label="简洁检索">Top K {agent.concise_top_k || 4} · 改写 {agent.concise_rewrite_count ?? 3} 条</Descriptions.Item>
                <Descriptions.Item label="详细检索">Top K {agent.detailed_top_k || 8} · 改写 {agent.detailed_rewrite_count ?? 3} 条</Descriptions.Item>
                <Descriptions.Item label="人格提示词" span={2}>{agent.persona_preset === 'custom' ? agent.persona_custom_instruction || '未填写' : personaPresets.find(item => item.key === agent.persona_preset)?.instruction}</Descriptions.Item>
                <Descriptions.Item label="可用状态">{agent.is_active ? <Tag color="green">已启用</Tag> : <Tag>已停用</Tag>}</Descriptions.Item>
                <Descriptions.Item label="描述" span={2}>{agent.description || '暂无描述'}</Descriptions.Item>
              </Descriptions></Card>
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
        ]} />
      </Card>

      <Modal title="挂载知识库" open={mountModalVisible} onOk={mountKnowledgeBases} onCancel={() => setMountModalVisible(false)} confirmLoading={mountModalLoading} okText="确认挂载" cancelText="取消" width={700}>
        <Table rowKey="id" loading={mountModalLoading} dataSource={availableKbList} columns={knowledgeColumns.slice(0, 4)} rowSelection={{ selectedRowKeys: selectedKbIds, onChange: (keys) => setSelectedKbIds(keys.map(Number)) }} pagination={{ pageSize: 6 }} size="small" locale={{ emptyText: '暂无可挂载的知识库' }} />
      </Modal>
      <Modal title="编辑 Agent" open={editingName} width={720} onCancel={() => setEditingName(false)} onOk={() => void saveName()}><Form form={nameForm} layout="vertical"><Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}><Input /></Form.Item><Form.Item name="description" label="描述"><Input.TextArea rows={2} maxLength={200} /></Form.Item><Form.Item name="context_window_k" label="上下文窗口" extra="默认 64K；系统会在上下文压力升高时自动裁剪和压缩。" rules={[{ required: true }]}><InputNumber min={32} max={256} addonAfter="K" style={{ width: '100%' }} /></Form.Item><section className="agent-retrieval-settings"><div className="agent-retrieval-heading"><div><Typography.Text strong>高级检索设置</Typography.Text><Typography.Text type="secondary">仅影响正式问答，不影响评测实验。</Typography.Text></div><Tag color="blue">默认策略</Tag></div><Row gutter={[12, 12]}><Col xs={24} sm={12}><div className="agent-retrieval-mode"><div className="agent-retrieval-mode-title"><b>简洁回答</b><span>默认：改写 3 · Top K 4</span></div><Row gutter={10}><Col span={12}><Form.Item name="concise_rewrite_count" label="改写数" rules={[{ required: true }]}><InputNumber min={0} max={5} addonAfter="条" style={{ width: '100%' }} /></Form.Item></Col><Col span={12}><Form.Item name="concise_top_k" label="Top K" rules={[{ required: true }]}><InputNumber min={1} max={20} addonAfter="条" style={{ width: '100%' }} /></Form.Item></Col></Row></div></Col><Col xs={24} sm={12}><div className="agent-retrieval-mode"><div className="agent-retrieval-mode-title"><b>详细回答</b><span>默认：改写 3 · Top K 8</span></div><Row gutter={10}><Col span={12}><Form.Item name="detailed_rewrite_count" label="改写数" rules={[{ required: true }]}><InputNumber min={0} max={5} addonAfter="条" style={{ width: '100%' }} /></Form.Item></Col><Col span={12}><Form.Item name="detailed_top_k" label="Top K" rules={[{ required: true }]}><InputNumber min={1} max={20} addonAfter="条" style={{ width: '100%' }} /></Form.Item></Col></Row></div></Col></Row></section><Form.Item noStyle shouldUpdate>{({ getFieldValue, setFieldValue }) => <Form.Item label="回答人格"><PersonaPicker value={getFieldValue('persona_preset') || 'professional'} customInstruction={getFieldValue('persona_custom_instruction') || ''} presets={personaPresets} editablePreset onChange={value => setFieldValue('persona_preset', value)} onCustomInstructionChange={value => setFieldValue('persona_custom_instruction', value)} onPresetInstructionChange={value => setPersonaPresets(items => items.map(item => item.key === getFieldValue('persona_preset') ? { ...item, instruction: value } : item))} /></Form.Item>}</Form.Item></Form></Modal>
    </div>
  )
}
