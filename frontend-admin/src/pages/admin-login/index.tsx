import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Card, QRCode, Space, Typography, message } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { api } from '@/services/api'

const { Title, Text } = Typography

interface Ticket { ticket_id: string; qr_payload: string; expires_at: string }
interface Poll { status: string; access_token?: string }

export default function AdminLogin() {
  const navigate = useNavigate()
  const [ticket, setTicket] = useState<Ticket | null>(null)
  const [loading, setLoading] = useState(false)

  const createTicket = async () => {
    setLoading(true)
    try { setTicket(await api.post<Ticket>('/admin/auth/tickets')) }
    catch { message.error('无法创建登录二维码') }
    finally { setLoading(false) }
  }

  useEffect(() => { createTicket() }, [])
  useEffect(() => {
    if (!ticket) return
    const timer = window.setInterval(async () => {
      try {
        const result = await api.get<Poll>(`/admin/auth/tickets/${ticket.ticket_id}`)
        if (result.access_token) {
          localStorage.setItem('zhida_admin_token', result.access_token)
          window.clearInterval(timer)
          navigate('/')
        } else if (result.status === 'expired') {
          window.clearInterval(timer)
          message.warning('二维码已过期，请刷新')
        }
      } catch { /* 网络瞬断时继续轮询 */ }
    }, 1500)
    return () => window.clearInterval(timer)
  }, [ticket, navigate])

  return <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', background: '#0f0f1a' }}>
    <Card style={{ width: 380, textAlign: 'center' }}>
      <Space direction="vertical" size="large">
        <Title level={3}>管理员扫码登录</Title>
        <Text type="secondary">使用“智答助手”小程序扫描二维码确认身份</Text>
        {ticket ? <QRCode value={ticket.qr_payload} size={220} /> : <Text>正在生成二维码…</Text>}
        <Button icon={<ReloadOutlined />} loading={loading} onClick={createTicket}>刷新二维码</Button>
      </Space>
    </Card>
  </div>
}
