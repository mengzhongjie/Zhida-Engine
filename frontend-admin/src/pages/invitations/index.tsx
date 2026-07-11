import { useCallback, useEffect, useState } from 'react'
import { Button, Card, DatePicker, Form, Input, InputNumber, message, Modal, Popconfirm, Space, Table, Tag, Typography } from 'antd'
import { PlusOutlined, ReloadOutlined, StopOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { api } from '@/services/api'

const { Title, Text } = Typography

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
  const [form] = Form.useForm()

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
        expires_at: values.expires_at ? values.expires_at.toISOString() : undefined,
        note: values.note || undefined,
      })
      Modal.success({
        title: '邀请码已创建',
        content: <Space direction="vertical"><Text>此邀请码仅显示一次，请立即复制：</Text><Text code copyable>{created.invite_code}</Text></Space>,
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

  const columns = [
    { title: '邀请码', dataIndex: 'code_hint', render: (v: string) => <Text code>******{v}</Text> },
    { title: '状态', dataIndex: 'status', render: (v: Invitation['status']) => <Tag color={{ active: 'green', claimed: 'blue', revoked: 'red', expired: 'default' }[v]}>{({ active: '待领取', claimed: '已领取', revoked: '已撤销', expired: '已过期' }[v])}</Tag> },
    { title: '每日问答', dataIndex: 'daily_question_limit', render: (v: number, r: Invitation) => `${r.usage_today} / ${v}` },
    { title: '失效时间', dataIndex: 'expires_at', render: (v: string | null) => v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '不失效' },
    { title: '备注', dataIndex: 'note', render: (v: string | null) => v || '-' },
    { title: '领取', dataIndex: 'claimed_at', render: (v: string | null) => v ? dayjs(v).format('YYYY-MM-DD HH:mm') : '-' },
    {
      title: '操作', key: 'action', render: (_: unknown, r: Invitation) => r.status === 'active' || r.status === 'claimed' ? (
        <Popconfirm title={r.status === 'claimed' ? '撤销后该用户将无法再使用小程序，确认继续？' : '确认使邀请码失效？'} onConfirm={() => revoke(r, r.status === 'claimed')}>
          <Button danger type="link" icon={<StopOutlined />}>{r.status === 'claimed' ? '撤销用户' : '失效'}</Button>
        </Popconfirm>
      ) : '-'
    },
  ]

  return <div>
    <Space style={{ marginBottom: 24, width: '100%', justifyContent: 'space-between' }}>
      <Title level={3} style={{ margin: 0 }}>邀请码</Title>
      <Button icon={<ReloadOutlined />} onClick={load}>刷新</Button>
    </Space>
    <Card title="创建一次性邀请码" style={{ marginBottom: 16 }} extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>创建邀请码</Button>}>
      <Text type="secondary">邀请码首次领取后会绑定一个微信账号。创建成功后，明文仅展示一次。</Text>
    </Card>
    <Card><Table rowKey="id" loading={loading} columns={columns} dataSource={items} pagination={{ pageSize: 10 }} /></Card>
    <Modal title="创建邀请码" open={creating} onCancel={() => setCreating(false)} onOk={create} okText="创建">
      <Form form={form} layout="vertical" initialValues={{ daily_question_limit: 2 }}>
        <Form.Item name="daily_question_limit" label="每日问答次数" rules={[{ required: true }]}><InputNumber min={1} max={1000} style={{ width: '100%' }} /></Form.Item>
        <Form.Item name="expires_at" label="失效时间"><DatePicker showTime style={{ width: '100%' }} /></Form.Item>
        <Form.Item name="note" label="备注"><Input.TextArea maxLength={500} rows={3} /></Form.Item>
      </Form>
    </Modal>
  </div>
}
