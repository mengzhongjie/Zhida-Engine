/**
 * 智答引擎（ZhiDa Engine）—— 新建 Agent 向导
 *
 * 3 步流程：基本信息 → 知识库选择 → 确认创建
 */
import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Card, Steps, Form, Input, InputNumber, Space, Typography, message,
  Table, Button, Segmented, Descriptions,
} from 'antd'
import {
  ArrowLeftOutlined, RobotOutlined, BookOutlined, CheckOutlined,
} from '@ant-design/icons'
import { api } from '../../services/api'
import PersonaPicker, { defaultPersonaPresets } from '../../components/PersonaPicker'
import type { PersonaPreset } from '../../components/PersonaPicker'

const { Title, Text } = Typography

interface KnowledgeBase {
  id: number
  name: string
  description: string
  doc_count: number
  chunk_count: number
  agent_id: number | null
  is_active: boolean
}

const steps = [
  { title: '基本信息', icon: <RobotOutlined /> },
  { title: '知识库', icon: <BookOutlined /> },
  { title: '确认创建', icon: <CheckOutlined /> },
]
export default function AgentNew() {
  const navigate = useNavigate()
  const [current, setCurrent] = useState(0)
  const [loading, setLoading] = useState(false)
  const [kbLoading, setKbLoading] = useState(false)

  const [kbList, setKbList] = useState<KnowledgeBase[]>([])
  const [kbFilter, setKbFilter] = useState<'all' | 'independent'>('all')
  const [personaPresets, setPersonaPresets] = useState<PersonaPreset[]>(defaultPersonaPresets)

  const [formData, setFormData] = useState({
    name: '',
    description: '',
    persona_preset: 'professional',
    persona_custom_instruction: '',
    context_window_k: 64,
    selected_kb_ids: [] as number[],
  })

  useEffect(() => {
    loadKnowledgeBases()
    api.get<PersonaPreset[]>('/admin/persona-presets').then(setPersonaPresets).catch(() => undefined)
  }, [])

  const loadKnowledgeBases = async () => {
    setKbLoading(true)
    try {
      const data = await api.get<{ items: KnowledgeBase[] }>('/knowledge/bases')
      setKbList(data.items || [])
    } catch (err) {
      console.error('加载知识库失败:', err)
      message.error('加载知识库失败')
    } finally {
      setKbLoading(false)
    }
  }

  const updateField = (field: string, value: any) => {
    setFormData((prev) => ({ ...prev, [field]: value }))
  }

  const next = () => setCurrent((prev) => Math.min(prev + 1, steps.length - 1))
  const prev = () => setCurrent((prev) => Math.max(prev - 1, 0))

  const handleCreate = async () => {
    if (!formData.name.trim()) {
      message.warning('请输入 Agent 名称')
      return
    }
    setLoading(true)
    try {
      const agent = await api.post<any>('/agents', {
        name: formData.name,
        description: formData.description,
        persona_preset: formData.persona_preset,
        persona_custom_instruction: formData.persona_custom_instruction,
        context_window_k: formData.context_window_k,
      })

      if (formData.selected_kb_ids.length > 0) {
        for (const kbId of formData.selected_kb_ids) {
          try {
            await api.post(`/knowledge/bases/${kbId}/attach`, { agent_id: agent.id })
          } catch (e) {
            console.error(`挂载知识库 ${kbId} 失败:`, e)
          }
        }
      }

      message.success(`Agent "${formData.name}" 创建成功！`)
      navigate('/agents')
    } catch {
      message.error('创建失败，请重试')
    } finally {
      setLoading(false)
    }
  }

  const filteredKbList = kbFilter === 'independent'
    ? kbList.filter((kb) => !kb.agent_id)
    : kbList

  const kbColumns = [
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '文档数', dataIndex: 'doc_count', key: 'doc_count', width: 100 },
    {
      title: '描述',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
      render: (v: string) => v || '-',
    },
    {
      title: '状态',
      dataIndex: 'agent_id',
      key: 'agent_id',
      width: 100,
      render: (v: number | null) => (
        <span style={{ color: v ? '#faad14' : '#52c41a' }}>
          {v ? '已挂载' : '可挂载'}
        </span>
      ),
    },
  ]

  const rowSelection = {
    selectedRowKeys: formData.selected_kb_ids,
    onChange: (selectedRowKeys: React.Key[]) => {
      setFormData((prev) => ({
        ...prev,
        selected_kb_ids: selectedRowKeys.map((k) => Number(k)),
      }))
    },
    getCheckboxProps: (record: KnowledgeBase) => ({
      disabled: !!record.agent_id,
    }),
  }

  const renderStep = () => {
    switch (current) {
      case 0:
        return (
          <div style={{ maxWidth: 500, margin: '0 auto' }}>
            <Form layout="vertical">
              <Form.Item label="Agent 名称" required>
                <Input
                  placeholder="例如：客服助手、技术问答"
                  value={formData.name}
                  onChange={(e) => updateField('name', e.target.value)}
                  maxLength={50}
                />
              </Form.Item>
              <Form.Item label="描述">
                <Input.TextArea
                  placeholder="描述这个 Agent 的用途..."
                  value={formData.description}
                  onChange={(e) => updateField('description', e.target.value)}
                  rows={3}
                  maxLength={200}
                />
              </Form.Item>
              <Form.Item label="回答人格">
                <PersonaPicker value={formData.persona_preset} customInstruction={formData.persona_custom_instruction} presets={personaPresets} onChange={(value) => updateField('persona_preset', value)} onCustomInstructionChange={(value) => updateField('persona_custom_instruction', value)} />
              </Form.Item>
              <Form.Item label="上下文窗口" extra="默认 64K；系统按占用比例自动裁剪和压缩。">
                <InputNumber min={32} max={256} addonAfter="K" value={formData.context_window_k} onChange={(value) => updateField('context_window_k', value || 64)} style={{ width: '100%' }} />
              </Form.Item>
            </Form>
          </div>
        )
      case 1:
        return (
          <div style={{ maxWidth: 800, margin: '0 auto' }}>
            <Title level={4} style={{ textAlign: 'center', marginBottom: 24 }}>
              选择挂载知识库
            </Title>
            <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <Segmented
                value={kbFilter}
                onChange={(v) => setKbFilter(v as 'all' | 'independent')}
                options={[
                  { label: '全部知识库', value: 'all' },
                  { label: '仅独立知识库', value: 'independent' },
                ]}
              />
              <Text type="secondary">
                已选择 {formData.selected_kb_ids.length} 个知识库
              </Text>
            </div>
            <Table
              rowKey="id"
              loading={kbLoading}
              dataSource={filteredKbList}
              columns={kbColumns}
              rowSelection={rowSelection}
              pagination={{ pageSize: 8 }}
              size="middle"
            />
            <Text type="secondary" style={{ display: 'block', marginTop: 12, textAlign: 'center' }}>
              创建后可在 Agent 详情页管理知识库
            </Text>
          </div>
        )
      case 2:
        return (
          <div style={{ maxWidth: 500, margin: '0 auto' }}>
            <Title level={4} style={{ textAlign: 'center' }}>确认创建</Title>
            <Card>
              <Descriptions column={1} bordered size="small">
                <Descriptions.Item label="名称">{formData.name || '未设置'}</Descriptions.Item>
                <Descriptions.Item label="回复方式">AI 回复</Descriptions.Item>
                <Descriptions.Item label="回答人格">{formData.persona_preset === 'custom' ? '自定义人格' : personaPresets.find(item => item.key === formData.persona_preset)?.name}</Descriptions.Item>
                <Descriptions.Item label="上下文窗口">{formData.context_window_k}K</Descriptions.Item>
                <Descriptions.Item label="人格提示词" span={2}>{formData.persona_preset === 'custom' ? formData.persona_custom_instruction || '未填写' : personaPresets.find(item => item.key === formData.persona_preset)?.instruction}</Descriptions.Item>
                <Descriptions.Item label="知识库">
                  {formData.selected_kb_ids.length > 0
                    ? `${formData.selected_kb_ids.length} 个知识库`
                    : '暂不挂载'}
                </Descriptions.Item>
              </Descriptions>
            </Card>
          </div>
        )
      default:
        return null
    }
  }

  return (
    <div className="content-page">
      <div style={{ marginBottom: 24 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>返回</Button>
      </div>

      <Card className="agent-new-card">
        <Title level={3} style={{ textAlign: 'center', marginBottom: 32 }}>
          <RobotOutlined style={{ marginRight: 8 }} />
          新建 Agent
        </Title>

        <Steps current={current} items={steps} style={{ marginBottom: 48 }} />

        <div style={{ minHeight: 300 }}>{renderStep()}</div>

        <div style={{ textAlign: 'center', marginTop: 32 }}>
          <Space>
            {current > 0 && <Button onClick={prev}>上一步</Button>}
            {current < steps.length - 1 && (
              <Button type="primary" onClick={next}>
                下一步
              </Button>
            )}
            {current === steps.length - 1 && (
              <Button type="primary" onClick={handleCreate} loading={loading}>
                确认创建
              </Button>
            )}
          </Space>
        </div>
      </Card>
    </div>
  )
}
