import { useCallback, useEffect, useState } from 'react'
import { Button, Card, Col, Row, Tag, Typography, message } from 'antd'
import { useNavigate } from 'react-router-dom'
import { ApiOutlined, ArrowLeftOutlined, DatabaseOutlined, DesktopOutlined } from '@ant-design/icons'
import { api } from '@/services/api'

const { Title, Text } = Typography

type SystemInfo = {
  app_name: string; app_version: string; python_version: string; platform: string
  data_dir: string; api_address: string; cpu_cores: number; memory_gb: number
  storage_type: string; resource_profile: string
}

export default function SystemInfoSettings() {
  const navigate = useNavigate()
  const [system, setSystem] = useState<SystemInfo | null>(null)
  const [loading, setLoading] = useState(false)
  const load = useCallback(async () => {
    setLoading(true)
    try { setSystem(await api.get<SystemInfo>('/admin/system-info')) }
    catch { message.error('加载系统信息失败') }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])

  return <div>
    <div className="page-header"><div><Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/settings')} style={{ marginLeft: -8 }}>返回设置</Button><Title level={3}>系统信息</Title><Text type="secondary">当前本地运行环境与服务信息。</Text></div></div>
    <Card loading={loading} style={{ maxWidth: 980, overflow: 'hidden' }} bodyStyle={{ padding: 0 }}>
      <div style={{ padding: '22px 24px', background: 'linear-gradient(120deg, #f0f7ff, #fafcff)', borderBottom: '1px solid #e6eef8' }}><div style={{ display: 'flex', alignItems: 'center', gap: 10 }}><DesktopOutlined style={{ color: '#1677ff', fontSize: 22 }} /><div><Text strong style={{ fontSize: 16 }}>运行环境</Text><br /><Text type="secondary">本机服务与资源概览</Text></div><Tag color="success" style={{ marginLeft: 'auto' }}>本地运行</Tag></div></div>
      <div style={{ padding: 24 }}><Row gutter={[14, 14]}><Col xs={12} md={6}><div style={{ padding: 14, border: '1px solid #edf0f5', borderRadius: 10 }}><Text type="secondary">应用版本</Text><div style={{ marginTop: 7, fontSize: 20, fontWeight: 600 }}>{system?.app_version || '-'}</div></div></Col><Col xs={12} md={6}><div style={{ padding: 14, border: '1px solid #edf0f5', borderRadius: 10 }}><Text type="secondary">CPU 核心</Text><div style={{ marginTop: 7, fontSize: 20, fontWeight: 600 }}>{system?.cpu_cores || '-'}</div></div></Col><Col xs={12} md={6}><div style={{ padding: 14, border: '1px solid #edf0f5', borderRadius: 10 }}><Text type="secondary">内存</Text><div style={{ marginTop: 7, fontSize: 20, fontWeight: 600 }}>{system?.memory_gb || '-'} <small style={{ fontSize: 12, fontWeight: 400 }}>GB</small></div></div></Col><Col xs={12} md={6}><div style={{ padding: 14, border: '1px solid #edf0f5', borderRadius: 10 }}><Text type="secondary">资源方案</Text><div style={{ marginTop: 7, fontSize: 20, fontWeight: 600 }}>{system?.resource_profile || '-'}</div></div></Col></Row><div style={{ marginTop: 22, display: 'grid', gap: 12 }}><div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}><DesktopOutlined style={{ color: '#64748b', marginTop: 3 }} /><Text type="secondary">{system?.platform || '-'} · Python {system?.python_version || '-'} · {system?.storage_type || '-'}</Text></div><div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}><ApiOutlined style={{ color: '#64748b', marginTop: 3 }} /><Text type="secondary">服务地址：{system?.api_address || '-'}</Text></div><div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}><DatabaseOutlined style={{ color: '#64748b', marginTop: 3 }} /><Text type="secondary">数据目录：{system?.data_dir || '-'}</Text></div></div></div>
    </Card>
  </div>
}
