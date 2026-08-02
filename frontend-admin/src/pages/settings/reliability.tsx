import { useCallback, useEffect, useState } from 'react'
import { Button, Card, Space, Statistic, Typography, message } from 'antd'
import { useNavigate } from 'react-router-dom'
import { ArrowLeftOutlined } from '@ant-design/icons'
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
    <Card title="运行环境" loading={loading} style={{ maxWidth: 900 }}>
      <Space wrap size="large"><Statistic title="应用版本" value={system?.app_version || '-'} /><Statistic title="CPU 核心" value={system?.cpu_cores || '-'} /><Statistic title="内存" value={system?.memory_gb || '-'} suffix="GB" /><Statistic title="资源方案" value={system?.resource_profile || '-'} /></Space>
      <div style={{ marginTop: 20 }}><Text type="secondary">{system?.platform || '-'} · Python {system?.python_version || '-'} · {system?.storage_type || '-'}<br />服务：{system?.api_address || '-'}<br />数据目录：{system?.data_dir || '-'}</Text></div>
    </Card>
  </div>
}
