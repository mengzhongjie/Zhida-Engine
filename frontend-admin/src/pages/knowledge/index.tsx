import { useCallback, useEffect, useState } from 'react'
import type { Key } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Card, Form, Input, Modal, Popconfirm, Space, Table, Tag, Typography, Upload, message } from 'antd'
import { DatabaseOutlined, DeleteOutlined, DownloadOutlined, FolderOpenOutlined, ImportOutlined, PlusOutlined } from '@ant-design/icons'
import type { UploadProps } from 'antd'
import { api } from '@/services/api'
import styles from './index.module.css'

const { Title, Text } = Typography
interface KnowledgeBase { id: number; name: string; description: string | null; document_count: number; chunk_count: number; total_size_bytes: number; capacity_status?: 'normal' | 'near_limit' | 'full'; document_limit?: number; size_limit_bytes?: number; is_active: boolean; updated_at: string }

export default function KnowledgeList() {
  const navigate = useNavigate()
  const [items, setItems] = useState<KnowledgeBase[]>([])
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [importing, setImporting] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Key[]>([])
  const [exportingIds, setExportingIds] = useState<number[]>([])
  const [deleting, setDeleting] = useState(false)
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
  const removeSelected = async () => {
    const ids = selectedIds.map(Number)
    if (!ids.length) return
    setDeleting(true)
    try {
      const result = await api.post<{ deleted: number[]; failed: { id: number; detail: string }[] }>('/knowledge/bases/batch-delete', { ids })
      if (result.deleted.length) message.success(`已删除 ${result.deleted.length} 个知识库`)
      if (result.failed.length) message.warning(result.failed.map(item => `#${item.id}：${item.detail}`).join('；'))
      setSelectedIds([])
      await load()
    } catch (error: any) {
      message.error(error?.response?.data?.detail || '批量删除失败')
    } finally { setDeleting(false) }
  }
  const importArchive: UploadProps['customRequest'] = async ({ file, onSuccess, onError }: any) => {
    setImporting(true)
    try {
      const body = new FormData(); body.append('file', file)
      const created = await api.post<KnowledgeBase>('/knowledge/bases/import', body, { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 120000 })
      message.success(`「${created.name}」已导入，正在按当前向量配置重新处理资料`)
      load(); onSuccess?.({}, file)
    } catch (error: any) { message.error(error?.response?.data?.detail || '导入失败'); onError?.(error) } finally { setImporting(false) }
  }
  const exportSelected = async () => {
    const ids = selectedIds.map(Number).filter(id => !exportingIds.includes(id))
    if (!ids.length) return
    setExportingIds(ids)
    try {
      for (const id of ids) {
        try {
          const item = items.find(value => value.id === id)
          const response = await fetch(`/api/v1/knowledge/bases/${id}/export`, { credentials: 'include' })
          if (!response.ok) {
            const detail = await response.json().catch(() => null) as { detail?: string } | null
            throw new Error(detail?.detail || `服务器返回 ${response.status}`)
          }
          const url = URL.createObjectURL(await response.blob())
          const link = document.createElement('a')
          link.href = url
          link.download = `${item?.name || '知识库'}.zip`
          link.style.display = 'none'
          document.body.appendChild(link)
          link.click()
          // 大文件下载可能不会在 click 后立即开始，延迟释放 Blob URL。
          window.setTimeout(() => { URL.revokeObjectURL(url); link.remove() }, 60_000)
        } catch (error: any) {
          message.error(`知识库 ${id} 导出失败：${error?.message || '未知错误'}`)
          return
        }
      }
    } finally {
      setExportingIds(previous => previous.filter(id => !ids.includes(id)))
    }
    message.success(`已开始导出 ${ids.length} 个知识库`)
  }
  const columns = [
    { title: '知识库', dataIndex: 'name', render: (name: string, item: KnowledgeBase) => <Space><DatabaseOutlined style={{ color: '#3aa7ff' }} /><div><Text strong>{name}</Text><br /><Text type="secondary">{item.description || '暂无描述'}</Text></div></Space> },
    { title: '文档', dataIndex: 'document_count', width: 100, render: (value: number) => <Tag color="blue">{value} 份</Tag> },
    { title: '切片', dataIndex: 'chunk_count', width: 100 },
    { title: '容量', width: 130, render: (_: unknown, item: KnowledgeBase) => { const status = item.capacity_status || 'normal'; const isExporting = exportingIds.includes(item.id); const color = isExporting ? 'processing' : status === 'full' ? 'error' : status === 'near_limit' ? 'warning' : 'success'; const label = isExporting ? '导出中' : status === 'full' ? '已达上限' : status === 'near_limit' ? '接近上限' : '正常'; return <Tag color={color}>{label}</Tag> } },
    { title: '状态', dataIndex: 'is_active', width: 100, render: (value: boolean) => <Tag color={value ? 'green' : 'default'}>{value ? '已启用' : '已停用'}</Tag> },
    { title: '操作', width: 250, render: (_: unknown, item: KnowledgeBase) => <Space><Button type="link" icon={<FolderOpenOutlined />} onClick={() => navigate(`/knowledge/${item.id}`)}>进入管理</Button><Popconfirm title="确认删除该知识库及其文档？" onConfirm={() => remove(item.id)}><Button type="link" danger icon={<DeleteOutlined />}>删除</Button></Popconfirm></Space> },
  ]
  return <div className={`${styles.container} content-page`}>
    <div className="page-header"><div><Title level={3}>知识库管理</Title><Text type="secondary" className="page-header-copy">统一管理资料、切片与可检索知识。</Text></div><Space><Button icon={<ImportOutlined />} onClick={() => setImportOpen(true)}>批量导入</Button><Button icon={<DownloadOutlined />} loading={exportingIds.length > 0} disabled={!selectedIds.length || exportingIds.length > 0} onClick={() => void exportSelected()}>批量导出 ({selectedIds.length})</Button><Popconfirm title="确认批量删除所选知识库及其文档？" description="处理中或清理失败的知识库会保留并返回原因。" onConfirm={() => void removeSelected()}><Button danger icon={<DeleteOutlined />} loading={deleting} disabled={!selectedIds.length || exportingIds.length > 0}>批量删除 ({selectedIds.length})</Button></Popconfirm><Button type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>新建知识库</Button></Space></div>
    <Card><Table rowKey="id" rowSelection={{ selectedRowKeys: selectedIds, onChange: setSelectedIds, getCheckboxProps: item => ({ disabled: exportingIds.includes(item.id) }) }} loading={loading} columns={columns} dataSource={items} pagination={{ pageSize: 10 }} locale={{ emptyText: '暂无知识库，先创建一个开始构建知识体系' }} /></Card>
    <Modal title="新建知识库" open={creating} onCancel={() => setCreating(false)} onOk={create} okText="创建"><Form form={form} layout="vertical"><Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}><Input maxLength={50} placeholder="例如：技术文档库" /></Form.Item><Form.Item name="description" label="描述"><Input.TextArea rows={3} maxLength={200} /></Form.Item></Form></Modal>
    <Modal title="批量导入知识库" open={importOpen} footer={null} onCancel={() => setImportOpen(false)}><Typography.Paragraph type="secondary">仅接受本系统导出的 ZIP；先校验清单 SHA-256，再校验每份原始资料哈希。不会导入模型密钥、用户会话、Agent 挂载或向量索引。</Typography.Paragraph><Upload.Dragger accept=".zip" multiple showUploadList disabled={importing} customRequest={importArchive}><p>{importing ? '正在校验并导入…' : '选择一个或多个知识库 ZIP'}</p><Text type="secondary">每个包最大 120 MB，最多 200 篇文档。</Text></Upload.Dragger></Modal>
  </div>
}
