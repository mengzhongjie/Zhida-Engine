import { useEffect, useState } from 'react'
import { Alert, Button, Card, Form, Input, Select, Switch, Tag, Typography, message } from 'antd'
import { useNavigate } from 'react-router-dom'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { api } from '@/services/api'

const { Title, Text } = Typography
type Config = { enabled: boolean; app_id: string; app_secret: string; last_test_success: boolean | null; last_error: string | null }
type SourceKey = 'feishu' | 'tencent-docs' | 'yuque'

const sourceOptions = [
  { value: 'feishu', label: '飞书', status: '已支持' },
  { value: 'tencent-docs', label: '腾讯文档', status: '规划中' },
  { value: 'yuque', label: '语雀', status: '规划中' },
]

export default function DataSourceSettings() {
  const navigate = useNavigate()
  const [source, setSource] = useState<SourceKey>('feishu')
  const [form] = Form.useForm()
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const load = async () => {
    try { const data = await api.get<Config>('/knowledge/feishu/config'); form.setFieldsValue({ ...data, app_secret: '' }) }
    catch { message.error('加载数据源配置失败') }
  }
  useEffect(() => { if (source === 'feishu') load() }, [source])
  const save = async () => {
    const values = await form.validateFields(); setSaving(true)
    try { await api.put('/knowledge/feishu/config', values); message.success('配置已保存'); load() }
    catch (e: any) { message.error(e?.response?.data?.detail || '保存失败') }
    finally { setSaving(false) }
  }
  const test = async () => {
    setTesting(true)
    try { const result = await api.post<{ success: boolean; message: string }>('/knowledge/feishu/config/test'); result.success ? message.success(result.message) : message.error(result.message); load() }
    catch { message.error('测试失败') }
    finally { setTesting(false) }
  }
  const selected = sourceOptions.find(item => item.value === source)!

  return <div>
    <div className="page-header"><div><Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/settings')} style={{ marginLeft: -8 }}>返回设置</Button><Title level={3}>数据源</Title><Text type="secondary">选择一个数据源后单独管理其授权与导入方式。</Text></div></div>
    <Card style={{ maxWidth: 720, marginBottom: 16 }}>
      <Form layout="vertical"><Form.Item label="数据源"><Select value={source} onChange={value => setSource(value)} options={sourceOptions.map(item => ({ value: item.value, label: <span>{item.label} <Tag style={{ marginLeft: 6 }} color={item.status === '已支持' ? 'success' : 'default'}>{item.status}</Tag></span> }))} /></Form.Item></Form>
    </Card>
    {source === 'feishu' ? <Card title="飞书配置" style={{ maxWidth: 720 }} extra={<Tag color="success">已支持</Tag>}>
      <Alert type="info" showIcon style={{ marginBottom: 20 }} message="无需创建聊天机器人" description="在飞书开放平台配置应用权限，并将目标文档或知识库授权给应用。第一期不读取私人云盘，也不需要用户 OAuth。" />
      <Form form={form} layout="vertical" initialValues={{ enabled: false }}><Form.Item name="enabled" label="启用此数据源" valuePropName="checked"><Switch /></Form.Item><Form.Item name="app_id" label="App ID" rules={[{ required: true, message: '请输入 App ID' }]}><Input autoComplete="off" placeholder="cli_xxx" /></Form.Item><Form.Item name="app_secret" label="App Secret" extra="已保存密钥不会回显；留空表示不修改"><Input.Password autoComplete="new-password" /></Form.Item><Button onClick={test} loading={testing}>测试连接</Button><Button type="primary" style={{ marginLeft: 8 }} onClick={save} loading={saving}>保存配置</Button></Form>
    </Card> : <Card title={`${selected.label}配置`} style={{ maxWidth: 720 }} extra={<Tag>规划中</Tag>}><Alert type="info" showIcon message="该数据源尚未接入" description="后续接入时会在这里提供独立的凭据、授权方式、连接测试和导入选项；不会复用或影响其他数据源的配置。" /></Card>}
  </div>
}
