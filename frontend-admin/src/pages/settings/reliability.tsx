import { useCallback, useEffect, useState } from 'react'
import { Button, Card, Col, Modal, Row, Switch, Tag, Typography, message } from 'antd'
import { useNavigate } from 'react-router-dom'
import { ApiOutlined, ArrowLeftOutlined, DatabaseOutlined, DesktopOutlined } from '@ant-design/icons'
import { api } from '@/services/api'

const { Title, Text } = Typography

type SystemInfo = {
  app_name: string; app_version: string; python_version: string; platform: string
  data_dir: string; api_address: string; cpu_cores: number; memory_gb: number
  storage_type: string; resource_profile: string
}

type ModuleSettings = { development_mode: boolean }

export default function SystemInfoSettings() {
  const navigate = useNavigate()
  const [system, setSystem] = useState<SystemInfo | null>(null)
  const [loading, setLoading] = useState(false)
  const [developmentMode, setDevelopmentMode] = useState(false)
  const [updatingDevelopmentMode, setUpdatingDevelopmentMode] = useState(false)
  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [systemInfo, moduleSettings] = await Promise.all([
        api.get<SystemInfo>('/admin/system-info'),
        api.get<ModuleSettings>('/admin/settings'),
      ])
      setSystem(systemInfo)
      setDevelopmentMode(moduleSettings.development_mode === true)
    }
    catch { message.error('加载系统信息失败') }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])

  const confirmDevelopmentMode = (next: boolean) => {
    Modal.confirm({
      title: next ? '开启开发维护模式？' : '关闭开发维护模式？',
      content: next
        ? '开启后，用户端会显示维护提示，且所有问答请求会被后端拒绝，不会消耗用户额度。'
        : '关闭后，用户端将立即恢复问答服务。',
      okText: next ? '确认开启' : '确认恢复服务',
      okButtonProps: next ? { danger: true } : undefined,
      cancelText: '取消',
      onOk: async () => {
        setUpdatingDevelopmentMode(true)
        try {
          const updated = await api.put<ModuleSettings>('/admin/settings', { development_mode: next })
          setDevelopmentMode(updated.development_mode === true)
          message.success(next ? '开发维护模式已开启' : '用户端问答已恢复')
        } catch {
          message.error('保存开发维护模式失败，请刷新后重试')
        } finally {
          setUpdatingDevelopmentMode(false)
        }
      },
    })
  }

  return <div>
    <div className="page-header"><div><Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/settings')} style={{ marginLeft: -8 }}>返回设置</Button><Title level={3}>系统信息</Title><Text type="secondary">当前本地运行环境与服务信息。</Text></div></div>
    <Card loading={loading} style={{ maxWidth: 980, overflow: 'hidden' }} bodyStyle={{ padding: 0 }}>
      <div style={{ padding: '22px 24px', background: 'linear-gradient(120deg, #f0f7ff, #fafcff)', borderBottom: '1px solid #e6eef8' }}><div style={{ display: 'flex', alignItems: 'center', gap: 10 }}><DesktopOutlined style={{ color: '#1677ff', fontSize: 22 }} /><div><Text strong style={{ fontSize: 16 }}>运行环境</Text><br /><Text type="secondary">本机服务与资源概览</Text></div><Tag color="success" style={{ marginLeft: 'auto' }}>本地运行</Tag></div></div>
      <div style={{ padding: 24 }}><Row gutter={[14, 14]}><Col xs={12} md={6}><div style={{ padding: 14, border: '1px solid #edf0f5', borderRadius: 10 }}><Text type="secondary">应用版本</Text><div style={{ marginTop: 7, fontSize: 20, fontWeight: 600 }}>{system?.app_version || '-'}</div></div></Col><Col xs={12} md={6}><div style={{ padding: 14, border: '1px solid #edf0f5', borderRadius: 10 }}><Text type="secondary">CPU 核心</Text><div style={{ marginTop: 7, fontSize: 20, fontWeight: 600 }}>{system?.cpu_cores || '-'}</div></div></Col><Col xs={12} md={6}><div style={{ padding: 14, border: '1px solid #edf0f5', borderRadius: 10 }}><Text type="secondary">内存</Text><div style={{ marginTop: 7, fontSize: 20, fontWeight: 600 }}>{system?.memory_gb || '-'} <small style={{ fontSize: 12, fontWeight: 400 }}>GB</small></div></div></Col><Col xs={12} md={6}><div style={{ padding: 14, border: '1px solid #edf0f5', borderRadius: 10 }}><Text type="secondary">资源方案</Text><div style={{ marginTop: 7, fontSize: 20, fontWeight: 600 }}>{system?.resource_profile || '-'}</div></div></Col></Row><div style={{ marginTop: 22, display: 'grid', gap: 12 }}><div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}><DesktopOutlined style={{ color: '#64748b', marginTop: 3 }} /><Text type="secondary">{system?.platform || '-'} · Python {system?.python_version || '-'} · {system?.storage_type || '-'}</Text></div><div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}><ApiOutlined style={{ color: '#64748b', marginTop: 3 }} /><Text type="secondary">服务地址：{system?.api_address || '-'}</Text></div><div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}><DatabaseOutlined style={{ color: '#64748b', marginTop: 3 }} /><Text type="secondary">数据目录：{system?.data_dir || '-'}</Text></div></div></div>
    </Card>
    <Card style={{ maxWidth: 980, marginTop: 16 }} title="服务维护">
      <Row justify="space-between" align="middle" gutter={[16, 12]}>
        <Col flex="auto"><Text strong>开发维护模式</Text><br /><Text type="secondary">暂停用户端问答并显示维护提示。后端会在额度扣减和模型调用前拒绝请求。</Text></Col>
        <Col><Tag color={developmentMode ? 'warning' : 'success'}>{developmentMode ? '维护中' : '正常服务'}</Tag><Switch checked={developmentMode} loading={updatingDevelopmentMode} onChange={confirmDevelopmentMode} aria-label="开发维护模式" /></Col>
      </Row>
    </Card>
  </div>
}
