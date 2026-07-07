/**
 * 智答引擎（ZhiDa Engine）—— 新建 Agent 向导
 *
 * 5 步流程：基本信息 → 选择平台 → 知识库 → 监听目标 → 确认创建
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Card, Steps, Form, Input, Select, Button, Radio, Space, Typography, message,
} from 'antd'
import {
  ArrowLeftOutlined, RobotOutlined, WechatOutlined, QqOutlined,
  BookOutlined, AimOutlined, CheckOutlined,
} from '@ant-design/icons'
import { api } from '../../services/api'

const { Title, Text } = Typography

const steps = [
  { title: '基本信息', icon: <RobotOutlined /> },
  { title: '选择平台', icon: <WechatOutlined /> },
  { title: '知识库', icon: <BookOutlined /> },
  { title: '监听目标', icon: <AimOutlined /> },
  { title: '确认创建', icon: <CheckOutlined /> },
]

export default function AgentNew() {
  const navigate = useNavigate()
  const [current, setCurrent] = useState(0)
  const [loading, setLoading] = useState(false)
  const [form] = Form.useForm()

  // 表单数据
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    reply_mode: 'auto',
    platform: 'wechat',
    enable_knowledge: true,
    enable_learning: true,
    chat_ids: '',
  })

  const updateField = (field: string, value: any) => {
    setFormData((prev) => ({ ...prev, [field]: value }))
  }

  const next = () => setCurrent((prev) => Math.min(prev + 1, steps.length - 1))
  const prev = () => setCurrent((prev) => Math.max(prev - 1, 0))

  // 创建 Agent
  const handleCreate = async () => {
    if (!formData.name.trim()) {
      message.warning('请输入 Agent 名称')
      return
    }
    setLoading(true)
    try {
      // 创建 Agent
      const agent = await api.post<any>('/agents', {
        name: formData.name,
        description: formData.description,
        reply_mode: formData.reply_mode,
      })

      message.success(`Agent "${formData.name}" 创建成功！`)
      navigate(`/agents/${agent.id}`)
    } catch (err) {
      message.error('创建失败，请重试')
    } finally {
      setLoading(false)
    }
  }

  // 渲染步骤内容
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
          <div style={{ maxWidth: 500, margin: '0 auto', textAlign: 'center' }}>
            <Title level={4}>选择消息平台</Title>
            <Space direction="vertical" size="large" style={{ width: '100%' }}>
              <Card
                hoverable
                style={{
                  border: formData.platform === 'wechat' ? '2px solid #1677ff' : '1px solid #333',
                  textAlign: 'center',
                }}
                onClick={() => updateField('platform', 'wechat')}
              >
                <WechatOutlined style={{ fontSize: 48, color: '#07c160' }} />
                <Title level={5}>微信</Title>
                <Text type="secondary">接入微信群，监听群聊消息</Text>
              </Card>
              <Card
                hoverable
                style={{
                  border: formData.platform === 'qq' ? '2px solid #1677ff' : '1px solid #333',
                  textAlign: 'center',
                }}
                onClick={() => updateField('platform', 'qq')}
              >
                <QqOutlined style={{ fontSize: 48, color: '#12b7f5' }} />
                <Title level={5}>QQ</Title>
                <Text type="secondary">接入 QQ 群，监听群聊消息</Text>
              </Card>
            </Space>
          </div>
        )
      case 2:
        return (
          <div style={{ maxWidth: 500, margin: '0 auto' }}>
            <Title level={4} style={{ textAlign: 'center' }}>知识库配置</Title>
            <Card style={{ marginBottom: 16 }}>
              <Form.Item label="启用知识库">
                <Radio.Group
                  value={formData.enable_knowledge}
                  onChange={(e) => updateField('enable_knowledge', e.target.value)}
                >
                  <Radio.Button value={true}>启用</Radio.Button>
                  <Radio.Button value={false}>暂不启用</Radio.Button>
                </Radio.Group>
              </Form.Item>
              <Text type="secondary">
                知识库用于上传文档（PDF/Word/Excel/TXT），Agent 将基于知识库内容回答问题。
              </Text>
            </Card>
            <Card>
              <Form.Item label="自动学习聊天知识">
                <Radio.Group
                  value={formData.enable_learning}
                  onChange={(e) => updateField('enable_learning', e.target.value)}
                >
                  <Radio.Button value={true}>启用</Radio.Button>
                  <Radio.Button value={false}>暂不启用</Radio.Button>
                </Radio.Group>
              </Form.Item>
              <Text type="secondary">
                自动从群聊中提取问答对，持续丰富知识库。
              </Text>
            </Card>
          </div>
        )
      case 3:
        return (
          <div style={{ maxWidth: 500, margin: '0 auto' }}>
            <Title level={4} style={{ textAlign: 'center' }}>监听目标</Title>
            <Form layout="vertical">
              <Form.Item label="群聊/联系人 ID">
                <Input.TextArea
                  placeholder="输入要监听的群聊 ID，每行一个&#10;例如：&#10;12345678@chatroom&#10;87654321@chatroom"
                  value={formData.chat_ids}
                  onChange={(e) => updateField('chat_ids', e.target.value)}
                  rows={5}
                />
              </Form.Item>
              <Text type="secondary">
                创建完成后，可在 Agent 详情页添加更多监听目标。
              </Text>
            </Form>
          </div>
        )
      case 4:
        return (
          <div style={{ maxWidth: 500, margin: '0 auto' }}>
            <Title level={4} style={{ textAlign: 'center' }}>确认创建</Title>
            <Card>
              <Descriptions column={1} bordered size="small">
                <Descriptions.Item label="名称">{formData.name || '未设置'}</Descriptions.Item>
                <Descriptions.Item label="回复模式">
                  {formData.reply_mode === 'auto' ? '自动' : formData.reply_mode === 'manual' ? '手动' : '混合'}
                </Descriptions.Item>
                <Descriptions.Item label="平台">
                  {formData.platform === 'wechat' ? '微信' : 'QQ'}
                </Descriptions.Item>
                <Descriptions.Item label="知识库">
                  {formData.enable_knowledge ? '启用' : '未启用'}
                </Descriptions.Item>
                <Descriptions.Item label="自动学习">
                  {formData.enable_learning ? '启用' : '未启用'}
                </Descriptions.Item>
                <Descriptions.Item label="监听目标">
                  {formData.chat_ids ? `${formData.chat_ids.split('\n').length} 个` : '未设置'}
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