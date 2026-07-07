/**
 * 智答引擎（ZhiDa Engine）—— 新建 Agent 向导
 *
 * 3 步流程：基本信息 → 知识库选择 → 确认创建
 */
import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Card, Steps, Form, Input, Radio, Space, Typography, message,
  Table, Button, Segmented, Descriptions,
} from 'antd'
import {
  ArrowLeftOutlined, RobotOutlined, BookOutlined, CheckOutlined,
} from '@ant-design/icons'
import { api } from '../../services/api'

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

  const [formData, setFormData] = useState({
    name: '',
    description: '',
    reply_mode: 'auto',
    selected_kb_ids: [] as number[],
  })

  useEffect(() => {
    loadKnowledgeBases()
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
        reply_mode: formData.reply_mode,
      })

      if (formData.selected_kb_ids.length > 0) {
        for (const kbId of formData.selected_kb_ids) {
          try {
            await api.put(`/knowledge/bases/${kbId}`, { agent_id: agent.id })
          } catch (e) {
            console.error(`挂载知识库 ${kbId} 失败:`, e)
          }
        }
      }

      message.success(`Agent "${formData.name}" 创建成功！`)
      navigate(`/agents/${agent.id}`)
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
              <Form.Item label="回复模式">
                <Radio.Group
                  value={formData.reply_mode}
                  onChange={(e) => updateField('reply_mode', e.target.value)}
                >
                  <Radio.Button value="auto">自动回复</Radio.Button>
                  <Radio.Button value="manual">手动回复</Radio.Button>
                  <Radio.Button value="hybrid">混合模式</Radio.Button>
                </Radio.Group>
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
                <Descriptions.Item label="回复模式">
                  {formData.reply_mode === 'auto' ? '自动回复' : formData.reply_mode === 'manual' ? '手动回复' : '混合模式'}
                </Descriptions.Item>
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
    <div>
      <div style={{ marginBottom: 24 }}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/')}>返回</Button>
      </div>

      <Card>
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
