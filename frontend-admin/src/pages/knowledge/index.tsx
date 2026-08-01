import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Card, Form, Input, Modal, Popconfirm, Space, Table, Tag, Typography, message } from 'antd'
import { DatabaseOutlined, DeleteOutlined, FolderOpenOutlined, PlusOutlined } from '@ant-design/icons'
import { api } from '@/services/api'
import styles from './index.module.css'

const { Title, Text } = Typography
interface KnowledgeBase { id: number; name: string; description: string | null; document_count: number; chunk_count: number; total_size_bytes: number; is_active: boolean; updated_at: string }

export default function KnowledgeList() {
  const navigate = useNavigate()
  const [items, setItems] = useState<KnowledgeBase[]>([])
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [form] = Form.useForm()
  const load = useCallback(async () => {
    setLoading(true)
    try { setItems((await api.get<{ items: KnowledgeBase[] }>('/knowledge/bases')).items || []) }
    catch { message.error('加载知识库失败') } finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])
  const create = async () => {
    const values = await form.validateFields()
    await api.post('/knowledge/bases', values)
    message.success('知识库已创建')
    form.resetFields(); setCreating(false); load()
  }
  const remove = async (id: number) => { await api.delete(`/knowledge/bases/${id}`); message.success('知识库已删除'); load() }
  const columns = [
    { title: '知识库', dataIndex: 'name', render: (name: string, item: KnowledgeBase) => <Space><DatabaseOutlined style={{ color: '#3aa7ff' }} /><div><Text strong>{name}</Text><br /><Text type="secondary">{item.description || '暂无描述'}</Text></div></Space> },
    { title: '文档', dataIndex: 'document_count', width: 100, render: (value: number) => <Tag color="blue">{value} 份</Tag> },
    { title: '切片', dataIndex: 'chunk_count', width: 100 },
    { title: '状态', dataIndex: 'is_active', width: 100, render: (value: boolean) => <Tag color={value ? 'green' : 'default'}>{value ? '已启用' : '已停用'}</Tag> },
    { title: '操作', width: 210, render: (_: unknown, item: KnowledgeBase) => <Space><Button type="link" icon={<FolderOpenOutlined />} onClick={() => navigate(`/knowledge/${item.id}`)}>进入管理</Button><Popconfirm title="确认删除该知识库及其文档？" onConfirm={() => remove(item.id)}><Button type="link" danger icon={<DeleteOutlined />}>删除</Button></Popconfirm></Space> },
  ]
  return <div className={`${styles.container} content-page`}>
    <div className="page-header"><div><Title level={3}>知识库管理</Title><Text type="secondary" className="page-header-copy">统一管理资料、切片与可检索知识。</Text></div><Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>新建知识库</Button></div>
    <Card><Table rowKey="id" loading={loading} columns={columns} dataSource={items} pagination={{ pageSize: 10 }} locale={{ emptyText: '暂无知识库，先创建一个开始构建知识体系' }} /></Card>
    <Modal title="新建知识库" open={creating} onCancel={() => setCreating(false)} onOk={create} okText="创建"><Form form={form} layout="vertical"><Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}><Input maxLength={50} placeholder="例如：技术文档库" /></Form.Item><Form.Item name="description" label="描述"><Input.TextArea rows={3} maxLength={200} /></Form.Item></Form></Modal>
  </div>
}
