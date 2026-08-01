import { useCallback, useEffect, useState } from 'react'
import { Button, Card, DatePicker, Form, Input, InputNumber, message, Modal, Popconfirm, Space, Table, Tag, Typography } from 'antd'
import { CopyOutlined, DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined, StopOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { api } from '@/services/api'

const { Title, Text } = Typography

const inviteCodeStyle = {
  color: '#56b6ff',
  background: 'rgba(22, 119, 255, 0.14)',
  borderColor: 'rgba(86, 182, 255, 0.42)',
}

interface Invitation {
  id: number
  code_hint: string
  daily_question_limit: number
  expires_at: string | null
  note: string | null
  status: 'active' | 'claimed' | 'revoked' | 'expired'
  claimed_at: string | null
  claimed_by_user_id: number | null
  created_at: string
  usage_today: number
}

interface CreatedInvitation extends Invitation {
  invite_code: string
}

export default function Invitations() {
  const [items, setItems] = useState<Invitation[]>([])
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [editing, setEditing] = useState<Invitation | null>(null)
  const [form] = Form.useForm()
  const [limitForm] = Form.useForm()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setItems(await api.get<Invitation[]>('/admin/invitations'))
    } catch {
      message.error('加载邀请码失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const create = async () => {
    const values = await form.validateFields()
    try {
      const created = await api.post<CreatedInvitation>('/admin/invitations', {
        daily_question_limit: values.daily_question_limit,
        // 后端 SQLite 使用无时区时间；按管理员在界面选择的本地时间提交。
        expires_at: values.expires_at ? values.expires_at.format('YYYY-MM-DDTHH:mm:ss') : undefined,
        note: values.note || undefined,
      })
      Modal.info({
        title: '邀请码已创建',
        icon: null,
        okText: '已复制，关闭',
        content: <div style={{ textAlign: 'center', padding: '16px 0' }}>
          <div style={{ marginBottom: 8 }}>此邀请码仅显示一次，请立即复制：</div>
          <Input value={created.invite_code} readOnly style={{ ...inviteCodeStyle, fontWeight: 700, fontSize: 20, textAlign: 'center', letterSpacing: 2, userSelect: 'all' }} />
          <Button type="primary" icon={<CopyOutlined />} style={{ marginTop: 14 }} onClick={async () => { await navigator.clipboard.writeText(created.invite_code); message.success('邀请码已复制') }}>复制邀请码</Button>
        </div>,
      })
      form.resetFields()
      setCreating(false)
      load()
    } catch (err: any) {
      if (!err?.errorFields) message.error(err?.response?.data?.detail || '创建邀请码失败')
    }
  }

  const revoke = async (record: Invitation, revokeUser = false) => {
    try {
      await api.post(`/admin/invitations/${record.id}/${revokeUser ? 'revoke-user' : 'revoke'}`)
      message.success(revokeUser ? '已撤销该用户访问资格' : '邀请码已失效')
      load()
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '操作失败')
    }
  }

  const remove = async (record: Invitation) => {
    try {
      await api.delete(`/admin/invitations/${record.id}`)
      message.success('邀请码已删除')
      load()
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '删除失败')
    }
  }

  const openLimitEditor = (record: Invitation) => {
    limitForm.setFieldsValue({ daily_question_limit: record.daily_question_limit })
    setEditing(record)
  }

  const saveDailyLimit = async () => {
    if (!editing) return
    const values = await limitForm.validateFields()
    try {
      await api.put(`/admin/invitations/${editing.id}/daily-limit`, values)
      message.success('每日问答次数已修改')
      setEditing(null)
      load()
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '修改失败')
    }
  }

  const columns = [
    { title: '邀请码', dataIndex: 'code_hint', render: (v: string) => <Text code style={inviteCodeStyle}>******{v}</Text> },
    { title: '状态', dataIndex: 'status', render: (v: Invitation['status']) => <Tag color={{ active: 'green', claimed: 'blue', revoked: 'red', expired: 'default' }[v]}>{({ active: '待领取', claimed: '已领取', revoked: '已撤销', expired: '已过期' }[v])}</Tag> },
    { title: '每日问答', dataIndex: 'daily_question_limit', render: (v: number, r: Invitation) => `${Math.min(Math.max(r.usage_today, 0), v)} / ${v}` },
    { title: '失效时间', dataIndex: 'expires_at', render: (v: string | null) => v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '不失效' },
    { title: '备注', dataIndex: 'note', render: (v: string | null) => v || '-' },
    { title: '领取', dataIndex: 'claimed_at', render: (v: string | null) => v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-' },
    {
      title: '操作', key: 'action', render: (_: unknown, r: Invitation) => (
        <Space size="small">
          <Button type="link" icon={<EditOutlined />} onClick={() => openLimitEditor(r)}>改次数</Button>
          {(r.status === 'active' || r.status === 'claimed') && (
            <Popconfirm title={r.status === 'claimed' ? '撤销后该用户将无法再使用小程序，确认继续？' : '确认使邀请码失效？'} onConfirm={() => revoke(r, r.status === 'claimed')}>
              <Button danger type="link" icon={<StopOutlined />}>{r.status === 'claimed' ? '撤销用户' : '失效'}</Button>
            </Popconfirm>
          )}
          <Popconfirm title={r.claimed_by_user_id ? '确认删除该邀请码额度池？若该用户还有其他邀请码，访问权限不会受影响。' : '确认永久删除该未领取的邀请码？'} onConfirm={() => remove(r)}>
              <Button danger type="link" icon={<DeleteOutlined />}>删除</Button>
          </Popconfirm>
        </Space>
      )
    },
  ]

  return <div className="content-page">
    <div className="page-header">
      <div><Title level={3}>邀请码</Title><Text type="secondary" className="page-header-copy">为微信用户分配一次性的访问权限与每日额度。</Text></div>
      <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
    </div>
    <Card title="创建一次性邀请码" style={{ marginBottom: 16 }} extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>创建邀请码</Button>}>
      <Text type="secondary">邀请码首次领取后会绑定一个微信账号。创建成功后，明文仅展示一次。</Text>
    </Card>
    <Card><Table rowKey="id" loading={loading} columns={columns} dataSource={items} pagination={{ pageSize: 10 }} /></Card>
    <Modal title="创建邀请码" open={creating} onCancel={() => setCreating(false)} onOk={create} okText="创建">
      <Form form={form} layout="vertical" initialValues={{ daily_question_limit: 2 }}>
        <Form.Item name="daily_question_limit" label="每日问答次数" rules={[{ required: true }]}><InputNumber min={1} max={1000} style={{ width: '100%' }} /></Form.Item>
        <Form.Item name="expires_at" label="失效时间"><DatePicker showTime style={{ width: '100%' }} /></Form.Item>
        <Form.Item label="快捷有效期">
          <Space>
            <Button htmlType="button" size="small" onClick={() => form.setFieldsValue({ expires_at: dayjs().add(1, 'day').endOf('day') })}>1 天</Button>
            <Button htmlType="button" size="small" onClick={() => form.setFieldsValue({ expires_at: dayjs().add(7, 'day').endOf('day') })}>7 天</Button>
            <Button htmlType="button" size="small" onClick={() => form.setFieldsValue({ expires_at: dayjs().add(30, 'day').endOf('day') })}>30 天</Button>
          </Space>
        </Form.Item>
        <Form.Item name="note" label="备注"><Input.TextArea maxLength={500} rows={3} /></Form.Item>
      </Form>
    </Modal>
    <Modal title="修改每日问答次数" open={!!editing} onCancel={() => setEditing(null)} onOk={saveDailyLimit} okText="保存">
      <Text type="secondary">仅修改此邀请码，不影响同一用户领取的其他邀请码。不能低于该邀请码今天已使用的次数。</Text>
      <Form form={limitForm} layout="vertical" style={{ marginTop: 16 }}>
        <Form.Item name="daily_question_limit" label="每日问答次数" rules={[{ required: true }]}>
          <InputNumber min={1} max={1000} style={{ width: '100%' }} />
        </Form.Item>
      </Form>
    </Modal>
  </div>
}
