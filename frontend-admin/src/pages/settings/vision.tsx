import { useEffect, useState } from 'react'
import { Alert, Button, Card, Form, Input, Modal, Popconfirm, Select, Space, Tag, Typography, message } from 'antd'
import { ArrowLeftOutlined, DeleteOutlined, EditOutlined, EyeOutlined, PlusOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api } from '@/services/api'

const { Title, Text } = Typography
type VisionConfig = {
  id: number; name: string; is_primary: boolean; is_fallback: boolean; enabled: boolean
  base_url: string; model_name: string; api_key: string; last_test_success: boolean | null; last_error: string | null
}

export default function VisionSettings() {
  const navigate = useNavigate()
  const [configs, setConfigs] = useState<VisionConfig[]>([])
  const [editing, setEditing] = useState<VisionConfig | null>(null)
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testingId, setTestingId] = useState<number | null>(null)
  const [form] = Form.useForm()
  const load = async () => { try { setConfigs(await api.get<VisionConfig[]>('/vision/configs')) } catch { message.error('加载视觉模型配置失败') } }
  useEffect(() => { load() }, [])

  const edit = (item?: VisionConfig) => {
    setEditing(item || null)
    form.setFieldsValue(item ? {
      name: item.name, base_url: item.base_url, model_name: item.model_name, api_key: '', enabled: item.enabled,
      role: item.is_primary ? 'primary' : item.is_fallback ? 'fallback' : 'standalone',
    } : { name: '视觉模型', enabled: true, role: configs.some(c => c.is_primary) ? 'fallback' : 'primary' })
    setOpen(true)
  }
  const save = async () => {
    const values = await form.validateFields(); setSaving(true)
    const payload = { ...values, enabled: editing?.enabled ?? true, is_primary: values.role === 'primary', is_fallback: values.role === 'fallback' }
    delete payload.role
    try {
      if (editing) await api.put(`/vision/configs/${editing.id}`, payload)
      else await api.post('/vision/configs', payload)
      setOpen(false); await load(); message.success('视觉模型配置已保存')
    } catch (e: any) { message.error(e?.response?.data?.detail || '保存失败') } finally { setSaving(false) }
  }
  const test = async (item: VisionConfig) => {
    setTestingId(item.id)
    try { const result = await api.post<{ success: boolean; message: string }>(`/vision/configs/${item.id}/test`); result.success ? message.success(result.message) : message.error(result.message); await load() }
    catch (e: any) { message.error(e?.response?.data?.detail || '测试失败') } finally { setTestingId(null) }
  }
  const toggle = async (item: VisionConfig) => {
    try { await api.put(`/vision/configs/${item.id}`, { ...item, api_key: '', enabled: !item.enabled }); await load(); message.success(item.enabled ? '已停用' : '已启用') }
    catch (e: any) { message.error(e?.response?.data?.detail || '更新状态失败') }
  }
  const remove = async (id: number) => { try { await api.delete(`/vision/configs/${id}`); await load(); message.success('已删除') } catch (e: any) { message.error(e?.response?.data?.detail || '删除失败') } }

  return <div>
    <div className="page-header"><div><Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/settings')} style={{ marginLeft: -8 }}>返回设置</Button><Title level={3}>视觉模型</Title><Text type="secondary">主模型不可用时，按已启用的降级配置继续处理图片。</Text></div><Button type="primary" icon={<PlusOutlined />} onClick={() => edit()}>新增配置</Button></div>
    <div className="web-search-settings"><Alert type="info" showIcon message="独立视觉链路" description="仅用于网页和云文档图片识别。测试会实际发送一张图片；降级模型只在主模型请求失败时调用。" />
      <div className="web-search-provider-list">{configs.map(item => {
        const health = item.last_test_success === true ? '可用' : item.last_test_success === false ? '不可用' : '待检测'
        return <Card key={item.id} size="small" className={`web-search-provider-card ${item.enabled ? 'is-active' : ''}`}>
          <div className="web-search-provider-main"><div><Space size={8}><EyeOutlined style={{ color: '#1677ff' }} /><Text strong>{item.name}</Text>{item.is_primary && <Tag color="blue">主模型</Tag>}{item.is_fallback && <Tag color="orange">降级</Tag>}</Space><Text type="secondary">{item.model_name || '尚未配置模型'}</Text></div><div className="web-search-provider-status"><Tag className={item.enabled ? 'search-chain-active' : undefined} color={item.enabled ? 'success' : 'default'}>{item.enabled ? '已启用' : '已停用'}</Tag><Text type={item.last_test_success === false ? 'danger' : 'secondary'}>{health}</Text></div></div>
          <Text className="web-search-health-copy" type="secondary">{item.last_error || (item.last_test_success ? '最近图片输入测试正常' : item.base_url || '等待配置')}</Text>
          <Space wrap className="web-search-provider-actions"><Button onClick={() => test(item)} loading={testingId === item.id}>测试连接</Button><Button icon={<EditOutlined />} onClick={() => edit(item)}>配置</Button><Button type={item.enabled ? 'default' : 'primary'} onClick={() => toggle(item)}>{item.enabled ? '停用' : '启用'}</Button><Popconfirm title="删除这条视觉配置？" onConfirm={() => remove(item.id)}><Button danger icon={<DeleteOutlined />} disabled={item.is_primary}>删除</Button></Popconfirm></Space>
        </Card>
      })}{!configs.length && <Card><Text type="secondary">暂无视觉模型配置。</Text></Card>}</div>
    </div>
    <Modal title={editing ? '编辑视觉模型' : '新增视觉模型'} open={open} onCancel={() => setOpen(false)} footer={null} destroyOnHidden><Form form={form} layout="vertical"><Form.Item name="name" label="配置名称" rules={[{ required: true }]}><Input placeholder="例如：Qwen VL 主模型" /></Form.Item><Form.Item name="role" label="角色" rules={[{ required: true }]}><Select options={[{ value: 'primary', label: '主模型' }, { value: 'fallback', label: '降级模型' }, { value: 'standalone', label: '独立备用（不进入链路）' }]} /></Form.Item><Form.Item name="base_url" label="API 地址" rules={[{ required: true, type: 'url', message: '请输入有效 API 地址' }]}><Input placeholder="https://api.siliconflow.cn/v1" /></Form.Item><Form.Item name="model_name" label="模型名称" rules={[{ required: true }]}><Input placeholder="例如 Qwen/Qwen3-VL-8B-Instruct" /></Form.Item><Form.Item name="api_key" label="API Key" extra={editing?.api_key ? `当前：${editing.api_key}；留空表示不修改` : ''}><Input.Password autoComplete="new-password" /></Form.Item><Button type="primary" onClick={save} loading={saving}>保存配置</Button></Form></Modal>
  </div>
}
