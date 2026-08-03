import { useEffect, useState } from 'react'
import { Alert, Button, Card, Form, Input, Modal, Space, Tag, Typography, message } from 'antd'
import { ArrowLeftOutlined, CloudOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api } from '@/services/api'

const { Title, Text } = Typography
type Config = { enabled: boolean; app_id: string; app_secret: string; last_test_success: boolean | null; last_error: string | null }

export default function CloudDocumentSettings() {
  const navigate = useNavigate()
  const [config, setConfig] = useState<Config | null>(null)
  const [form] = Form.useForm()
  const [modalOpen, setModalOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)

  const load = async () => {
    try { setConfig(await api.get<Config>('/knowledge/feishu/config')) }
    catch { message.error('加载云文档配置失败') }
  }
  useEffect(() => { load() }, [])

  const openConfig = () => {
    form.setFieldsValue({ app_id: config?.app_id || '', app_secret: '' })
    setModalOpen(true)
  }
  const save = async () => {
    const values = await form.validateFields()
    setSaving(true)
    try {
      await api.put('/knowledge/feishu/config', { ...values, enabled: config?.enabled || false })
      setModalOpen(false); await load(); message.success('云文档配置已保存')
    } catch (e: any) { message.error(e?.response?.data?.detail || '保存失败') }
    finally { setSaving(false) }
  }
  const test = async () => {
    setTesting(true)
    try {
      const result = await api.post<{ success: boolean; message: string }>('/knowledge/feishu/config/test')
      result.success ? message.success(result.message) : message.error(result.message)
      await load()
    } catch (e: any) { message.error(e?.response?.data?.detail || '测试失败') }
    finally { setTesting(false) }
  }
  const toggle = async () => {
    if (!config?.enabled && (!config?.app_id || !config?.app_secret)) { message.warning('请先配置 App ID 与 App Secret'); return }
    try {
      await api.put('/knowledge/feishu/config', { enabled: !config?.enabled, app_id: config?.app_id || '' })
      await load(); message.success(config?.enabled ? '云文档已停用' : '云文档已启用')
    } catch (e: any) { message.error(e?.response?.data?.detail || '更新状态失败') }
  }

  const health = config?.last_test_success === true ? '可用' : config?.last_test_success === false ? '不可用' : '待检测'
  return <div>
    <div className="page-header"><div><Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/settings')} style={{ marginLeft: -8 }}>返回设置</Button><Title level={3}>云文档配置</Title><Text type="secondary">管理可导入知识库的外部云文档来源。</Text></div></div>
    <div className="web-search-settings">
      <Alert type="info" showIcon message="应用身份读取" description="将目标文档或知识空间授权给应用即可导入，无需创建聊天机器人，也不读取私人云盘。" />
      <div className="web-search-provider-list">
        <Card size="small" className={`web-search-provider-card ${config?.enabled ? 'is-active' : ''}`}>
          <div className="web-search-provider-main"><div><Space size={8}><CloudOutlined style={{ color: '#1677ff' }} /><Text strong>飞书云文档</Text></Space><Text type="secondary">导入 Docx 文档与知识库节点</Text></div><div className="web-search-provider-status"><Tag className={config?.enabled ? 'search-chain-active' : undefined} color={config?.enabled ? 'success' : 'default'}>{config?.enabled ? '已启用' : '未启用'}</Tag><Text type={config?.last_test_success === false ? 'danger' : 'secondary'}>{health}</Text></div></div>
          <Text className="web-search-health-copy" type="secondary">{config?.last_error || (config?.last_test_success ? '最近测试连接正常' : '请完成配置后测试连接')}</Text>
          <Space wrap className="web-search-provider-actions"><Button onClick={test} loading={testing}>测试连接</Button><Button onClick={openConfig}>配置</Button><Button type={config?.enabled ? 'default' : 'primary'} onClick={toggle}>{config?.enabled ? '停用' : '启用'}</Button></Space>
        </Card>
      </div>
    </div>
    <Modal title="配置飞书云文档" open={modalOpen} onCancel={() => setModalOpen(false)} footer={null} destroyOnHidden>
      <Form form={form} layout="vertical"><Form.Item name="app_id" label="App ID" rules={[{ required: true, message: '请输入 App ID' }]}><Input autoComplete="off" placeholder="cli_xxx" /></Form.Item><Form.Item name="app_secret" label="App Secret" extra="已保存密钥不会回显；留空表示不修改"><Input.Password autoComplete="new-password" /></Form.Item><Button type="primary" onClick={save} loading={saving}>保存配置</Button></Form>
    </Modal>
  </div>
}
