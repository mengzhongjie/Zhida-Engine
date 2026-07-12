import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Card, Popconfirm, Space, Table, Tag, Typography, message } from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined, PoweroffOutlined } from '@ant-design/icons'
import { api } from '@/services/api'
import zhidaLogo from '../../assets/zhida-logo.png'

const { Title, Text } = Typography
interface Agent { id: number; name: string; description: string; is_public: boolean; status: string; today_answers: number; success_rate: number }
export default function AgentList() {
  const navigate = useNavigate(); const [items, setItems] = useState<Agent[]>([]); const [loading, setLoading] = useState(false)
  const load = useCallback(async () => { setLoading(true); try { setItems((await api.get<{ items: Agent[] }>('/agents')).items || []) } catch { message.error('加载 Agent 失败') } finally { setLoading(false) } }, [])
  useEffect(() => { load() }, [load])
  const toggle = async (agent: Agent) => { await api.post(`/agents/${agent.id}/${agent.status === 'running' ? 'stop' : 'start'}`); message.success(agent.status === 'running' ? 'Agent 已停止' : 'Agent 已启动'); load() }
  const remove = async (id: number) => { await api.delete(`/agents/${id}`); message.success('Agent 已删除'); load() }
  const columns = [
    { title: 'Agent', dataIndex: 'name', render: (name: string, item: Agent) => <Space><img src={zhidaLogo} alt="智答" style={{ width: 36, height: 36, borderRadius: 9 }} /><div><Text strong>{name}</Text><br /><Text type="secondary">{item.description || '暂无描述'}</Text></div></Space> },
    { title: '运行状态', dataIndex: 'status', width: 110, render: (v: string) => <Tag color={v === 'running' ? 'green' : 'default'}>{v === 'running' ? '运行中' : '已停止'}</Tag> },
    { title: '小程序', dataIndex: 'is_public', width: 110, render: (v: boolean) => <Tag color={v ? 'blue' : 'default'}>{v ? '已公开' : '未公开'}</Tag> },
    { title: '今日回答', dataIndex: 'today_answers', width: 110 }, { title: '成功率', dataIndex: 'success_rate', width: 100, render: (v: number) => `${v}%` },
    { title: '操作', width: 260, render: (_: unknown, agent: Agent) => <Space><Button type="link" icon={<EditOutlined />} onClick={() => navigate(`/agents/${agent.id}`)}>管理</Button><Button type="link" icon={<PoweroffOutlined />} onClick={() => toggle(agent)}>{agent.status === 'running' ? '停止' : '启动'}</Button><Popconfirm title="确认删除该 Agent？" onConfirm={() => remove(agent.id)}><Button danger type="link" icon={<DeleteOutlined />}>删除</Button></Popconfirm></Space> },
  ]
  return <div><div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}><div><Title level={3} style={{ margin: 0 }}>Agent 管理</Title><Text type="secondary">从列表进入单个 Agent，管理知识库、小程序公开状态与运行状态。</Text></div><Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/agents/new')}>新建 Agent</Button></div><Card><Table rowKey="id" loading={loading} columns={columns} dataSource={items} pagination={{ pageSize: 10 }} locale={{ emptyText: '暂无 Agent，创建一个开始配置' }} /></Card></div>
}
