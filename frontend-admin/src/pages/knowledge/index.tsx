import { useCallback, useEffect, useState } from 'react'
import type { Key } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Card, Form, Input, Modal, Popconfirm, Space, Table, Tag, Typography, Upload, message } from 'antd'
import { DatabaseOutlined, DeleteOutlined, DownloadOutlined, FolderOpenOutlined, ImportOutlined, PlusOutlined } from '@ant-design/icons'
import type { UploadProps } from 'antd'
import { api } from '@/services/api'
import styles from './index.module.css'

const { Title, Text } = Typography
interface KnowledgeBase { id: number; name: string; description: string | null; document_count: number; chunk_count: number; total_size_bytes: number; is_active: boolean; updated_at: string }

export default function KnowledgeList() {
  const navigate = useNavigate()
  const [items, setItems] = useState<KnowledgeBase[]>([])
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [importing, setImporting] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Key[]>([])
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
  const importArchive: UploadProps['customRequest'] = async ({ file, onSuccess, onError }: any) => {
    setImporting(true)
    try {
      const body = new FormData(); body.append('file', file)
      const created = await api.post<KnowledgeBase>('/knowledge/bases/import', body, { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 120000 })
      message.success(`「${created.name}」已导入，正在按当前向量配置重新处理资料`)
      load(); onSuccess?.({}, file)
    } catch (error: any) { message.error(error?.response?.data?.detail || '导入失败'); onError?.(error) } finally { setImporting(false) }
  }
  const exportSelected = async () => { for (const id of selectedIds) { try { const item = items.find(value => value.id === id); const response = await fetch(`/api/v1/knowledge/bases/${id}/export`, { credentials: 'include' }); if (!response.ok) throw new Error(); const url = URL.createObjectURL(await response.blob()); const link = document.createElement('a'); link.href = url; link.download = `${item?.name || '知识库'}.zip`; link.click(); URL.revokeObjectURL(url) } catch { message.error(`知识库 ${id} 导出失败`); return } } message.success(`已开始导出 ${selectedIds.length} 个知识库`) }
  const columns = [
    { title: '知识库', dataIndex: 'name', render: (name: string, item: KnowledgeBase) => <Space><DatabaseOutlined style={{ color: '#3aa7ff' }} /><div><Text strong>{name}</Text><br /><Text type="secondary">{item.description || '暂无描述'}</Text></div></Space> },
    { title: '文档', dataIndex: 'document_count', width: 100, render: (value: number) => <Tag color="blue">{value} 份</Tag> },
    { title: '切片', dataIndex: 'chunk_count', width: 100 },
    { title: '状态', dataIndex: 'is_active', width: 100, render: (value: boolean) => <Tag color={value ? 'green' : 'default'}>{value ? '已启用' : '已停用'}</Tag> },
    { title: '操作', width: 210, render: (_: unknown, item: KnowledgeBase) => <Space><Button type="link" icon={<FolderOpenOutlined />} onClick={() => navigate(`/knowledge/${item.id}`)}>进入管理</Button><Popconfirm title="确认删除该知识库及其文档？" onConfirm={() => remove(item.id)}><Button type="link" danger icon={<DeleteOutlined />}>删除</Button></Popconfirm></Space> },
  ]
  return <div className={`${styles.container} content-page`}>
    <div className="page-header"><div><Title level={3}>知识库管理</Title><Text type="secondary" className="page-header-copy">统一管理资料、切片与可检索知识。</Text></div><Space><Button icon={<ImportOutlined />} onClick={() => setImportOpen(true)}>批量导入</Button><Button icon={<DownloadOutlined />} disabled={!selectedIds.length} onClick={() => void exportSelected()}>批量导出 ({selectedIds.length})</Button><Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>新建知识库</Button></Space></div>
    <Card><Table rowKey="id" rowSelection={{ selectedRowKeys: selectedIds, onChange: setSelectedIds }} loading={loading} columns={columns} dataSource={items} pagination={{ pageSize: 10 }} locale={{ emptyText: '暂无知识库，先创建一个开始构建知识体系' }} /></Card>
    <Modal title="新建知识库" open={creating} onCancel={() => setCreating(false)} onOk={create} okText="创建"><Form form={form} layout="vertical"><Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}><Input maxLength={50} placeholder="例如：技术文档库" /></Form.Item><Form.Item name="description" label="描述"><Input.TextArea rows={3} maxLength={200} /></Form.Item></Form></Modal>
    <Modal title="批量导入知识库" open={importOpen} footer={null} onCancel={() => setImportOpen(false)}><Typography.Paragraph type="secondary">仅接受本系统导出的 ZIP；先校验清单 SHA-256，再校验每份原始资料哈希。不会导入模型密钥、用户会话、Agent 挂载或向量索引。</Typography.Paragraph><Upload.Dragger accept=".zip" multiple showUploadList disabled={importing} customRequest={importArchive}><p>{importing ? '正在校验并导入…' : '选择一个或多个知识库 ZIP'}</p><Text type="secondary">每个包最大 200 MB，最多 1000 篇文档。</Text></Upload.Dragger></Modal>
  </div>
}
