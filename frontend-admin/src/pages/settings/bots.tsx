import { useEffect, useState } from 'react'
import { Button, Card, Space, Tag, Typography, message } from 'antd'
import { ArrowLeftOutlined, QqOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api } from '@/services/api'

type QQConfig = { enabled: boolean; app_id: string; last_test_success: boolean | null; last_error: string | null }

export default function BotSettings() {
  const navigate = useNavigate(); const [config, setConfig] = useState<QQConfig>(); const [testing, setTesting] = useState(false)
  const load = async () => { try { setConfig(await api.get<QQConfig>('/qq-bot/config')) } catch { message.error('加载机器人配置失败') } }
  useEffect(() => { void load() }, [])
  const test = async () => { setTesting(true); try { const result = await api.post<{ success: boolean; message: string }>('/qq-bot/config/test'); result.success ? message.success(result.message) : message.error(result.message); await load() } catch (error: any) { message.error(error?.response?.data?.detail || '测试失败') } finally { setTesting(false) } }
  const toggle = async () => { try { await api.put('/qq-bot/config', { enabled: !config?.enabled, app_id: config?.app_id || '' }); await load(); message.success(config?.enabled ? 'QQ 机器人已停用' : 'QQ 机器人已启用') } catch (error: any) { message.error(error?.response?.data?.detail || '更新失败') } }
  const health = config?.last_test_success === true ? '可用' : config?.last_test_success === false ? '不可用' : '待检测'
  return <div><div className="page-header"><div><Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/settings')} style={{ marginLeft: -8 }}>返回设置</Button><Typography.Title level={3}>机器人</Typography.Title><Typography.Text type="secondary">统一管理外部消息平台；每个平台独立配置凭据和 Agent 绑定。</Typography.Text></div></div><div className="web-search-provider-list"><Card className={`web-search-provider-card ${config?.enabled ? 'is-active' : ''}`}><div className="web-search-provider-main"><div><Space size={8}><QqOutlined style={{ color: '#1677ff' }} /><Typography.Text strong>QQ 官方机器人</Typography.Text></Space><Typography.Paragraph type="secondary" style={{ margin: '6px 0 0' }}>群内 @机器人 后由绑定 Agent 回答</Typography.Paragraph></div><div className="web-search-provider-status"><Tag className={config?.enabled ? 'search-chain-active' : undefined} color={config?.enabled ? 'success' : 'default'}>{config?.enabled ? '已启用' : '未启用'}</Tag><Typography.Text type={config?.last_test_success === false ? 'danger' : 'secondary'}>{health}</Typography.Text></div></div><Typography.Text className="web-search-health-copy" type="secondary">{config?.last_error || (config?.enabled ? '已启用 QQ Gateway 连接' : '完成凭据配置后即可启用')}</Typography.Text><Space wrap className="web-search-provider-actions"><Button onClick={test} loading={testing}>测试凭据</Button><Button onClick={() => navigate('/settings/bots/qq')}>配置</Button><Button type={config?.enabled ? 'default' : 'primary'} onClick={toggle}>{config?.enabled ? '停用' : '启用'}</Button></Space></Card></div></div>
}
