import { useEffect, useState } from 'react'
import { Button, Card, Form, Input, Segmented, Typography, message } from 'antd'
import { LockOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import zhidaLogo from '../../assets/zhida-logo.png'

const { Text, Title } = Typography
type Captcha = { captcha_id: string; image_url: string }

function readableError(detail: unknown, fallback: string) {
  if (typeof detail === 'string' && detail.trim()) return detail
  if (Array.isArray(detail)) {
    const fields = detail.map(item => {
      if (typeof item === 'string') return item
      if (item && typeof item === 'object' && 'msg' in item && typeof item.msg === 'string') {
        const field = Array.isArray((item as { loc?: unknown }).loc) ? (item as { loc: unknown[] }).loc.at(-1) : ''
        const label = field === 'password' ? '密码' : field === 'username' ? '管理员账号' : field === 'access_code' ? '激活码' : field === 'captcha_answer' ? '图形验证码' : '输入内容'
        const minimum = (item as { ctx?: { min_length?: unknown } }).ctx?.min_length
        if (typeof minimum === 'number' && item.msg.includes('at least')) return `${label}至少需要 ${minimum} 个字符`
        if (item.msg.includes('Field required')) return `请填写${label}`
        return item.msg
      }
      return ''
    }).filter(Boolean)
    if (fields.length) return fields.join('；')
  }
  if (detail && typeof detail === 'object' && 'message' in detail && typeof detail.message === 'string') return detail.message
  return fallback
}

export default function LoginPage({ fixedRole }: { fixedRole?: 'user' | 'admin' }) {
  const navigate = useNavigate()
  const [form] = Form.useForm()
  const [role, setRole] = useState<'user' | 'admin'>(fixedRole || 'user')
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [captcha, setCaptcha] = useState<Captcha>()
  const [loading, setLoading] = useState(false)

  const loadCaptcha = async () => {
    try {
      const response = await fetch(`/api/v1/auth/captcha?purpose=${role}`, { credentials: 'include' })
      const data = await response.json().catch(() => ({}))
      if (!response.ok || !data.image_url || !data.captcha_id) throw new Error(readableError(data.detail, '验证码服务不可用'))
      setCaptcha(data)
    } catch (error: any) {
      setCaptcha(undefined)
      message.error(error?.message || '验证码加载失败，请确认后端已重启')
    }
  }

  useEffect(() => {
    form.resetFields(['captcha_answer'])
    void loadCaptcha()
  }, [role])

  const switchMode = (next: 'login' | 'register') => {
    setMode(next)
    form.resetFields()
  }

  const submit = async () => {
    const values = await form.validateFields()
    if (!captcha) return message.warning('请先加载图形验证码')
    setLoading(true)
    try {
      const endpoint = mode === 'register' ? '/api/v1/auth/admin/register' : `/api/v1/auth/${role}/login`
      const body = { ...values, captcha_id: captcha.captcha_id }
      if (mode === 'register') delete body.confirm
      const response = await fetch(endpoint, {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(readableError(data.detail, mode === 'register' ? '注册失败' : '登录失败'))
      navigate(mode === 'register' || role === 'admin' ? '/' : '/user', { replace: true })
    } catch (error: any) {
      message.error(error.message || '登录失败')
      await loadCaptcha()
    } finally {
      setLoading(false)
    }
  }

  return <main className="login-page">
    <div className="login-shell">
      <section className="login-intro">
        <div className="login-intro-brand"><img src={zhidaLogo} alt="智答引擎" /><span>智答引擎</span></div>
        <div>
          <Title level={1}>让知识，随时可问</Title>
          <p>连接专属知识库，获取有依据的智能回答。</p>
        </div>
        <div className="login-intro-note"><span />本服务由管理员配置与维护</div>
      </section>

      <Card className="login-card">
        <div className="login-form-heading">
          <Text className="login-eyebrow">WELCOME</Text>
          <Title level={3}>{mode === 'register' ? '注册管理员' : role === 'user' ? '登录你的助手' : '登录管理台'}</Title>
          <Text type="secondary">{mode === 'register' ? '首次部署请先注册管理员账号。' : role === 'user' ? '使用管理员提供的一次性激活码首次进入。' : '使用管理员账号安全进入系统。'}</Text>
        </div>
        {!fixedRole && <Segmented block value={role} onChange={value => setRole(value as 'user' | 'admin')} options={[{ label: '用户登录', value: 'user' }, { label: '管理端', value: 'admin' }]} />}
        <Form form={form} layout="vertical" onFinish={submit} className="login-form">
          {role === 'user'
            ? <Form.Item name="access_code" label="激活码" rules={[{ required: true, message: '请输入激活码' }, { min: 16, message: '激活码长度不正确' }]}><Input prefix={<LockOutlined />} placeholder="输入一次性激活码" autoComplete="one-time-code" /></Form.Item>
            : <><Form.Item name="username" label="管理员账号" rules={[{ required: true, message: '请输入管理员账号' }, mode === 'register' ? { min: 3, message: '账号至少 3 个字符' } : {}]}><Input prefix={<SafetyCertificateOutlined />} autoComplete="username" /></Form.Item><Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }, mode === 'register' ? { min: 8, message: '密码至少 8 位' } : {}]}><Input.Password prefix={<LockOutlined />} autoComplete={mode === 'register' ? 'new-password' : 'current-password'} /></Form.Item>{mode === 'register' && <Form.Item name="confirm" label="确认密码" dependencies={['password']} rules={[{ required: true, message: '请再次输入密码' }, ({ getFieldValue }) => ({ validator: (_, value) => !value || getFieldValue('password') === value ? Promise.resolve() : Promise.reject(new Error('两次输入的密码不一致')) })]}><Input.Password prefix={<LockOutlined />} autoComplete="new-password" /></Form.Item>}</>}
          <Form.Item name="captcha_answer" label="图形验证码" rules={[{ required: true, message: '请输入验证码' }]}>
            <div className="captcha-row"><Input placeholder="验证码" autoComplete="off" /><button type="button" className="captcha-image" onClick={() => void loadCaptcha()} title="点击更换验证码">{captcha ? <img src={captcha.image_url} alt="图形验证码" onError={() => { setCaptcha(undefined); message.error('验证码图片无法显示，请点击刷新') }} /> : <span>点击加载</span>}</button></div>
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={loading}>{mode === 'register' ? '注册并进入' : role === 'user' ? '激活并进入' : '登录'}</Button>
        </Form>
        {role === 'admin' && mode === 'login' && <div className="register-hint"><Text type="secondary">首次部署？</Text><Button type="link" onClick={() => switchMode('register')}>注册管理员账号</Button></div>}
        {role === 'admin' && mode === 'register' && <div className="register-hint"><Text type="secondary">已有账号？</Text><Button type="link" onClick={() => switchMode('login')}>返回登录</Button></div>}
      </Card>
    </div>
  </main>
}
