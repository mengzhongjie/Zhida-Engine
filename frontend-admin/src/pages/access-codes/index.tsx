import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Table, Tag, Typography, message } from 'antd'
import { CopyOutlined, DeleteOutlined, EditOutlined, KeyOutlined, PlusOutlined, ReloadOutlined, StopOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { api } from '@/services/api'

const { Text, Title } = Typography
type Agent = { id: number; name: string; is_active: boolean }
type AccessCode = { id: number; code_hint: string; status: 'active' | 'claimed' | 'revoked' | 'expired'; daily_question_limit: number; usage_today: number; expires_at?: string | null; claimed_at?: string | null; note?: string | null; created_at: string; agents: { id: number; name: string }[] }
type CreatedCode = { id: number; access_code: string; code_hint: string }
const errorText = (error: any, fallback: string) => typeof error?.response?.data?.detail === 'string' ? error.response.data.detail : fallback

export default function AccessCodes() {
  const [items, setItems] = useState<AccessCode[]>([])
  const [agents, setAgents] = useState<Agent[]>([])
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<AccessCode>()
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [createdCodes, setCreatedCodes] = useState<CreatedCode[]>([])
  const [lookupCode, setLookupCode] = useState('')
  const [form] = Form.useForm()
  const [limitForm] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [codes, agentData] = await Promise.all([api.get<{ items: AccessCode[] }>('/auth/admin/access-codes'), api.get<{ items: Agent[] }>('/agents')])
      setItems(codes.items || [])
      setAgents(agentData.items || [])
      setSelectedIds(previous => previous.filter(id => (codes.items || []).some(item => item.id === id)))
    } catch (error: any) {
      if (error?.response?.status !== 401) message.error(errorText(error, '加载兑换码失败'))
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { void load() }, [load])

  const copy = async (text: string, success = '兑换码已复制') => {
    try { await navigator.clipboard.writeText(text); message.success(success) } catch { Modal.info({ title: '请手动复制', content: <Input.TextArea value={text} autoSize readOnly /> }) }
  }

  const create = async () => {
    const values = await form.validateFields()
    try {
      const created = await api.post<{ items: CreatedCode[] }>('/auth/admin/access-codes', values)
      setCreating(false); form.resetFields(); setCreatedCodes(created.items || []); void load()
    } catch (error: any) { if (!error?.errorFields) message.error(errorText(error, '创建兑换码失败')) }
  }

  const updateLimit = async () => {
    if (!editing) return
    try { const values = await limitForm.validateFields(); await api.put(`/auth/admin/access-codes/${editing.id}/daily-limit`, values); message.success('额度已更新'); setEditing(undefined); void load() } catch (error: any) { if (!error?.errorFields) message.error(errorText(error, '更新失败')) }
  }
  const revoke = async (item: AccessCode) => { try { await api.post(`/auth/admin/access-codes/${item.id}/revoke`); message.success('兑换码已停用'); void load() } catch (error) { message.error(errorText(error, '停用失败')) } }
  const copyCode = async (item: AccessCode) => { try { const result = await api.post<CreatedCode & { rotated: boolean }>(`/auth/admin/access-codes/${item.id}/copy`); await copy(result.access_code, result.rotated ? '历史兑换码已换发并复制，原码已失效' : '兑换码已复制'); if (result.rotated) void load() } catch (error) { message.error(errorText(error, '复制兑换码失败')) } }
  const copySelected = async () => { try { const result = await api.post<{ items: { id: number; access_code: string }[]; rotated_count: number; unavailable_count: number }>('/auth/admin/access-codes/copy/batch', { ids: selectedIds }); const suffix = result.unavailable_count ? `；${result.unavailable_count} 个已激活或失效，未导出` : ''; await copy(result.items.map(item => item.access_code).join('\n'), `所选未激活码已复制${suffix}`); if (result.rotated_count || result.unavailable_count) void load() } catch (error) { message.error(errorText(error, '批量复制失败')) } }
  const resetActivation = async (item: AccessCode) => { try { const result = await api.post<CreatedCode>(`/auth/admin/access-codes/${item.id}/reset-activation`); setCreatedCodes([result]); message.success('已换发新激活码，原登录 Cookie 已失效'); void load() } catch (error) { message.error(errorText(error, '重置登录失败')) } }
  const remove = async (item: AccessCode) => { try { await api.delete(`/auth/admin/access-codes/${item.id}`); message.success('兑换码已删除'); void load() } catch (error) { message.error(errorText(error, '删除失败')) } }
  const removeSelected = async () => { try { const result = await api.post<{ deleted: number }>('/auth/admin/access-codes/batch/delete', { ids: selectedIds }); message.success(`已删除 ${result.deleted} 个兑换码`); setSelectedIds([]); void load() } catch (error) { message.error(errorText(error, '批量删除失败')) } }
  const lookup = async () => { const access_code = lookupCode.trim(); if (!access_code) return; try { const found = await api.post<AccessCode>('/auth/admin/access-codes/lookup', { access_code }); setItems(previous => [found, ...previous.filter(item => item.id !== found.id)]); setLookupCode(''); message.success(`已定位兑换码 ••••-${found.code_hint}`) } catch (error) { message.error(errorText(error, '未找到对应兑换码')) } }

  const columns = [
    { title: '激活码', width: 220, render: (_: unknown, item: AccessCode) => <Space size="small" wrap={false} style={{ whiteSpace: 'nowrap' }}><Text code style={{ whiteSpace: 'nowrap' }}>••••-{item.code_hint}</Text>{item.status === 'active' && <Button type="link" size="small" icon={<CopyOutlined />} onClick={() => void copyCode(item)}>复制</Button>}</Space> },
    { title: '授权 Agent', dataIndex: 'agents', render: (value: AccessCode['agents']) => <Space size={[4, 4]} wrap>{value.map(agent => <Tag key={agent.id}>{agent.name}</Tag>)}</Space> },
    { title: '额度', render: (_: unknown, item: AccessCode) => `${item.usage_today} / ${item.daily_question_limit}` },
    { title: '状态', dataIndex: 'status', render: (status: AccessCode['status']) => <Tag color={status === 'active' ? 'green' : status === 'claimed' ? 'blue' : status === 'expired' ? 'default' : 'red'}>{status === 'active' ? '待激活' : status === 'claimed' ? '已激活' : status === 'expired' ? '已过期' : '已停用'}</Tag> },
    { title: '有效期', dataIndex: 'expires_at', render: (value?: string | null) => value ? dayjs(value).format('YYYY-MM-DD HH:mm') : '长期有效' },
    { title: '备注', dataIndex: 'note', render: (value?: string | null) => value || '—' },
    { title: '操作', key: 'action', width: 350, fixed: 'right' as const, render: (_: unknown, item: AccessCode) => <Space size="small" wrap={false} style={{ whiteSpace: 'nowrap' }}><Button type="link" icon={<EditOutlined />} onClick={() => { setEditing(item); limitForm.setFieldsValue({ daily_question_limit: item.daily_question_limit }) }}>额度</Button>{item.status === 'claimed' && <Popconfirm title="将注销该用户的所有设备，并换发一个新的单次激活码。用户历史保留，确认继续？" onConfirm={() => void resetActivation(item)}><Button type="link" icon={<KeyOutlined />}>重置登录</Button></Popconfirm>}{(item.status === 'active' || item.status === 'claimed') && <Popconfirm title="停用后该用户将立即无法继续访问，确认继续？" onConfirm={() => void revoke(item)}><Button type="link" danger icon={<StopOutlined />}>停用</Button></Popconfirm>}<Popconfirm title="确认删除？这会永久删除该用户的会话历史与访问资格。" onConfirm={() => void remove(item)}><Button type="link" danger icon={<DeleteOutlined />}>删除</Button></Popconfirm></Space> },
  ]

  return <div className="content-page access-code-page"><div className="page-header"><div><Title level={3}>用户激活码</Title><Text type="secondary" className="page-header-copy">为用户授予指定 Agent 的访问权限与每日问答额度。</Text></div><Space wrap><Input.Search aria-label="查询旧兑换码" value={lookupCode} onChange={event => setLookupCode(event.target.value)} onSearch={() => void lookup()} placeholder="输入旧兑换码查询" style={{ width: 240 }} enterButton="查询" /><Button icon={<ReloadOutlined />} onClick={() => void load()}>刷新</Button><Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>新建激活码</Button></Space></div>
    <Card className="access-code-overview"><Text strong>激活码只能领取一次</Text><Text type="secondary">用户首次登录后，完整激活码会立即销毁，无法再次查看或使用。用户丢失登录状态时，请使用“重置登录”换发新码。</Text></Card>
    {selectedIds.length > 0 && <div className="access-code-batch"><span>已选择 {selectedIds.length} 个兑换码</span><Button size="small" icon={<CopyOutlined />} onClick={() => void copySelected()}>批量复制</Button><Popconfirm title={`确认删除选中的 ${selectedIds.length} 个兑换码？`} onConfirm={() => void removeSelected()}><Button danger size="small" icon={<DeleteOutlined />}>批量删除</Button></Popconfirm><Button size="small" onClick={() => setSelectedIds([])}>取消</Button></div>}
    <Card><Table rowKey="id" loading={loading} rowSelection={{ selectedRowKeys: selectedIds, onChange: keys => setSelectedIds(keys.map(Number)) }} columns={columns} dataSource={items} scroll={{ x: 1240 }} pagination={{ pageSize: 10 }} locale={{ emptyText: '暂无兑换码' }} /></Card>
    <Modal title="新建用户激活码" open={creating} onCancel={() => setCreating(false)} onOk={() => void create()} okText="创建"><Alert type="info" showIcon style={{ marginBottom: 16 }} message="仅可授权已启用的 Agent" description="激活码仅首次登录有效；领取后完整码会立即销毁。停止 Agent 后，已激活用户也会立即不可访问。" /><Form form={form} layout="vertical" initialValues={{ daily_question_limit: 50, count: 1 }}><Form.Item name="agent_ids" label="授权 Agent" rules={[{ required: true, message: '至少选择一个 Agent' }]}><Select mode="multiple" placeholder="选择可访问的 Agent" options={agents.map(agent => ({ value: agent.id, label: agent.is_active ? agent.name : `${agent.name}（未启用）`, disabled: !agent.is_active }))} /></Form.Item><Form.Item name="count" label="生成数量" rules={[{ required: true }]}><InputNumber min={1} max={100} style={{ width: '100%' }} /></Form.Item><Form.Item name="daily_question_limit" label="每日问答额度" rules={[{ required: true }]}><InputNumber min={1} max={10000} style={{ width: '100%' }} /></Form.Item><Form.Item name="expires_days" label="有效天数（留空则长期有效）"><InputNumber min={1} max={3650} style={{ width: '100%' }} /></Form.Item><Form.Item label="快捷有效期"><Space wrap><Button size="small" onClick={() => form.setFieldValue('expires_days', 1)}>1 天</Button><Button size="small" onClick={() => form.setFieldValue('expires_days', 7)}>7 天</Button><Button size="small" onClick={() => form.setFieldValue('expires_days', 30)}>30 天</Button><Button size="small" onClick={() => form.setFieldValue('expires_days', undefined)}>长期</Button></Space></Form.Item><Form.Item name="note" label="备注"><Input.TextArea rows={3} maxLength={500} placeholder="例如：测试用户 / 某个客户" /></Form.Item></Form></Modal>
    <Modal title={`已生成 ${createdCodes.length} 个激活码`} open={createdCodes.length > 0} onCancel={() => setCreatedCodes([])} footer={<Space><Button onClick={() => setCreatedCodes([])}>关闭</Button><Button type="primary" icon={<CopyOutlined />} onClick={() => void copy(createdCodes.map(item => item.access_code).join('\n'), '全部激活码已复制')}>复制全部</Button></Space>}><div className="access-code-created"><Text>请在用户首次登录前安全分发；被领取后无法再次查看。</Text><Input.TextArea value={createdCodes.map(item => item.access_code).join('\n')} autoSize={{ minRows: 3, maxRows: 10 }} readOnly /></div></Modal>
    <Modal title="调整每日额度" open={!!editing} onCancel={() => setEditing(undefined)} onOk={() => void updateLimit()} okText="保存"><Form form={limitForm} layout="vertical"><Form.Item name="daily_question_limit" label="每日问答额度" rules={[{ required: true }]}><InputNumber min={1} max={10000} style={{ width: '100%' }} /></Form.Item></Form></Modal>
  </div>
}
