import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Alert, Button, Card, Col, Form, Input, Modal, Popconfirm, Row, Space, Statistic, Switch, Table, Tag, Typography, Upload, message } from 'antd'
import { ArrowLeftOutlined, DeleteOutlined, FileTextOutlined, InboxOutlined, SaveOutlined } from '@ant-design/icons'
import type { UploadProps } from 'antd'
import { api } from '@/services/api'

const { Title, Text } = Typography
const { Dragger } = Upload
interface KB { id: number; name: string; description: string | null; document_count: number; chunk_count: number; total_size_bytes: number; is_active: boolean; index_status?: string; embedding_model?: string }
interface Doc { id: number; filename: string; file_type: string; file_size: number; status: string; chunk_count: number; error_message?: string; duplicate?: boolean; parse_time_ms?: number; split_time_ms?: number; embedding_time_ms?: number; total_time_ms?: number; processing_stage?: string; failed_stage?: string; processing_attempts?: number }
const states: Record<string, { color: string; text: string }> = {
  pending: { color: 'default', text: '等待/重试中' }, processing: { color: 'processing', text: '处理中' }, completed: { color: 'success', text: '已入库' }, error: { color: 'error', text: '处理失败' }, cleanup_pending: { color: 'warning', text: '待清理' },
}
const stageNames: Record<string, string> = { preparing: '准备任务', parsing: '解析文档', splitting: '切分文本', indexing: '向量化与写入', cleanup: '清理向量', completed: '完成' }
const duration = (ms?: number) => ms ? `${(ms / 1000).toFixed(ms > 10000 ? 1 : 2)} 秒` : '—'

export default function KnowledgeDetail() {
  const { id } = useParams<{ id: string }>(); const navigate = useNavigate()
  const [kb, setKb] = useState<KB | null>(null); const [docs, setDocs] = useState<Doc[]>([]); const [loading, setLoading] = useState(false); const [uploading, setUploading] = useState(false); const [editing, setEditing] = useState(false); const [form] = Form.useForm()
  const load = useCallback(async (showLoading = true) => { if (!id) return; if (showLoading) setLoading(true); try { const [base, documentList] = await Promise.all([api.get<KB>(`/knowledge/bases/${id}`), api.get<{ items: Doc[] }>(`/knowledge/documents?kb_id=${id}`)]); setKb(base); setDocs(documentList.items || []) } catch { message.error('加载知识库详情失败') } finally { if (showLoading) setLoading(false) } }, [id])
  useEffect(() => { load() }, [load])
  const active = docs.some(d => ['pending', 'processing', 'cleanup_pending'].includes(d.status))
  useEffect(() => { if (!active) return; const timer = window.setInterval(() => load(false), 2500); return () => window.clearInterval(timer) }, [active, load])
  const upload: UploadProps['customRequest'] = async ({ file, onSuccess, onError }: any) => { setUploading(true); try { const body = new FormData(); body.append('file', file); const document = await api.post<Doc>(`/knowledge/bases/${id}/upload`, body, { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 120000 }); message.info(document.duplicate ? `${file.name} 已存在，未重复入库` : `${file.name} 已接收，正在后台处理`); onSuccess?.({}, file); load() } catch (error) { message.error(`${file.name} 上传失败`); onError?.(error) } finally { setUploading(false) } }
  const save = async () => { const values = await form.validateFields(); await api.put(`/knowledge/bases/${id}`, values); setEditing(false); message.success('知识库已更新'); load() }
  const removeDoc = async (docId: number) => { try { await api.delete(`/knowledge/documents/${docId}`); message.success('文档及向量已删除') } catch { message.warning('向量清理尚未完成，已保留为待清理状态；请稍后重试删除') } finally { load() } }
  if (!kb) return <Card loading />
  const columns = [
    { title: '文档与任务', dataIndex: 'filename', render: (name: string, d: Doc) => <div><Text strong>{name}</Text><span className="task-detail">{d.processing_stage && `阶段：${stageNames[d.processing_stage] || d.processing_stage}`} · 尝试 {d.processing_attempts || 0} 次 · 总耗时 {duration(d.total_time_ms)}</span>{d.error_message && <Text type="danger" className="task-detail">{d.error_message}</Text>}</div> },
    { title: '类型', dataIndex: 'file_type', width: 90, render: (v: string) => <Tag>{v.toUpperCase()}</Tag> },
    { title: '状态', dataIndex: 'status', width: 110, render: (v: string) => <Tag color={(states[v] || {}).color}>{(states[v] || { text: v }).text}</Tag> },
    { title: '耗时', width: 155, render: (_: unknown, d: Doc) => <Text type="secondary">解析 {duration(d.parse_time_ms)}<br />切分 {duration(d.split_time_ms)} · 向量 {duration(d.embedding_time_ms)}</Text> },
    { title: '切片', dataIndex: 'chunk_count', width: 75 },
    { title: '操作', width: 96, render: (_: unknown, d: Doc) => <Popconfirm title={d.status === 'cleanup_pending' ? '再次尝试清理向量？' : '确认删除此文档及其向量？'} onConfirm={() => removeDoc(d.id)}><Button type="link" danger icon={<DeleteOutlined />}>{d.status === 'cleanup_pending' ? '重试清理' : '删除'}</Button></Popconfirm> },
  ]
  return <div>
    <div className="knowledge-hero"><Space><Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/knowledge')}>知识库</Button><div><Title level={3} style={{ margin: 0 }}>{kb.name}</Title><Text type="secondary">{kb.description || '集中管理可检索的业务资料'}</Text></div></Space><Button icon={<SaveOutlined />} onClick={() => { form.setFieldsValue(kb); setEditing(true) }}>编辑</Button></div>
    <Row gutter={[16, 16]} style={{ marginBottom: 20 }}><Col xs={24} md={8}><Card><Statistic title="文档" value={kb.document_count} prefix={<FileTextOutlined />} /></Card></Col><Col xs={24} md={8}><Card><Statistic title="知识切片" value={kb.chunk_count} /></Card></Col><Col xs={24} md={8}><Card><Statistic title="存储占用" value={(kb.total_size_bytes / 1024 / 1024).toFixed(1)} suffix="MB" /></Card></Col></Row>
    <Card title="添加资料" style={{ marginBottom: 20 }}>{kb.index_status === 'rebuild_required' && <Alert style={{ marginBottom: 14 }} type="warning" showIcon message="索引需要重建" description="当前向量配置与已有索引不一致。请先运行知识库重建脚本，再继续上传，避免混用不同模型的向量。" />}<Dragger multiple disabled={uploading || kb.index_status === 'rebuild_required'} customRequest={upload} accept=".pdf,.docx,.xlsx,.txt,.md,.csv,.json"><p className="ant-upload-drag-icon"><InboxOutlined /></p><p>{uploading ? '正在上传…' : '拖入文件，或点击选择文件'}</p><Text type="secondary">文件在后台处理，不会阻塞当前页面。支持失败后自动重试。</Text></Dragger>{active && <Alert style={{ marginTop: 14 }} type="info" showIcon message="后台任务正在执行" description="页面会自动刷新进度；每个文档会展示当前阶段、重试次数和耗时。" />}</Card>
    <Card title="资料处理记录" extra={<Button onClick={() => load()}>刷新</Button>}><Table rowKey="id" loading={loading} columns={columns} dataSource={docs} pagination={{ pageSize: 10 }} scroll={{ x: 780 }} /></Card>
    <Modal title="编辑知识库" open={editing} onCancel={() => setEditing(false)} onOk={save}><Form form={form} layout="vertical"><Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="description" label="描述"><Input.TextArea rows={3} /></Form.Item><Form.Item name="is_active" valuePropName="checked" label="启用"><Switch /></Form.Item></Form></Modal>
  </div>
}
