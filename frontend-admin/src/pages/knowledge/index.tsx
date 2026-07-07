/**
 * 智答引擎 - 知识库管理页面
 *
 * 文档上传、文档列表、知识库优化、统计信息
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Card, Table, Button, Upload, message, Space, Tag, Typography,
  Row, Col, Statistic, Popconfirm, Modal, Form, Input, Select, Switch,
} from 'antd'
import {
  DeleteOutlined, FileTextOutlined, FilePdfOutlined,
  FileExcelOutlined, FileWordOutlined, SyncOutlined, InboxOutlined,
  PlusOutlined, EditOutlined, DatabaseOutlined, SettingOutlined,
} from '@ant-design/icons'
import type { UploadProps } from 'antd'
import { api } from '@/services/api'
import styles from './index.module.css'

const { Text } = Typography
const { Dragger } = Upload
const { Option } = Select

interface KnowledgeBase {
  id: number
  name: string
  description: string | null
  agent_id: number | null
  document_count: number
  chunk_count: number
  total_size_bytes: number
  is_active: boolean
  created_at: string
  updated_at: string
}

interface BackendDocument {
  id: number
  knowledge_base_id: number
  filename: string
  file_type: string
  file_size: number
  status: string
  error_message: string | null
  chunk_count: number
  parse_time_ms: number
  created_at: string
  updated_at: string
}

const fileTypeIcon = (type: string) => {
  if (type.includes('pdf')) return <FilePdfOutlined style={{ color: '#ff4d4f' }} />
  if (type.includes('word') || type.includes('docx')) return <FileWordOutlined style={{ color: '#1890ff' }} />
  if (type.includes('excel') || type.includes('xlsx')) return <FileExcelOutlined style={{ color: '#52c41a' }} />
  return <FileTextOutlined />
}

const formatSize = (bytes: number) => {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

const statusMap: Record<string, { color: string; text: string }> = {
  pending: { color: 'default', text: '等待中' },
  processing: { color: 'processing', text: '解析中' },
  completed: { color: 'success', text: '已解析' },
  error: { color: 'error', text: '失败' },
}

export default function KnowledgePage() {
  const [bases, setBases] = useState<KnowledgeBase[]>([])
  const [selectedBaseId, setSelectedBaseId] = useState<number | null>(null)
  const [documents, setDocuments] = useState<BackendDocument[]>([])
  const [docTotal, setDocTotal] = useState(0)
  const [docPage, setDocPage] = useState(1)
  const [docPageSize, setDocPageSize] = useState(10)
  const [loadingBases, setLoadingBases] = useState(false)
  const [loadingDocs, setLoadingDocs] = useState(false)
  const [uploading, setUploading] = useState(false)

  const [createModalOpen, setCreateModalOpen] = useState(false)
  const [editModalOpen, setEditModalOpen] = useState(false)
  const [editingBase, setEditingBase] = useState<KnowledgeBase | null>(null)
  const [form] = Form.useForm()

  const selectedBase = bases.find((b) => b.id === selectedBaseId) || null

  const loadBases = useCallback(async () => {
    setLoadingBases(true)
    try {
      const res = await api.get<{ total: number; items: KnowledgeBase[] }>('/knowledge/bases')
      setBases(res.items || [])
      if (res.items?.length && !selectedBaseId) {
        setSelectedBaseId(res.items[0].id)
      }
    } catch (err) {
      console.error('加载知识库列表失败:', err)
      message.error('加载知识库列表失败')
    } finally {
      setLoadingBases(false)
    }
  }, [])

  const loadDocuments = useCallback(async () => {
    if (!selectedBaseId) return
    setLoadingDocs(true)
    try {
      const res = await api.get<{ total: number; items: BackendDocument[] }>(
        `/knowledge/documents?kb_id=${selectedBaseId}`
      )
      setDocuments(res.items || [])
      setDocTotal(res.total || 0)
    } catch (err) {
      console.error('加载文档列表失败:', err)
    } finally {
      setLoadingDocs(false)
    }
  }, [selectedBaseId])

  useEffect(() => {
    loadBases()
  }, [loadBases])

  useEffect(() => {
    if (selectedBaseId) {
      setDocPage(1)
      loadDocuments()
    }
  }, [selectedBaseId])

  const handleCreateBase = async (values: { name: string; description: string }) => {
    try {
      await api.post('/knowledge/bases', values)
      message.success('知识库创建成功')
      setCreateModalOpen(false)
      form.resetFields()
      loadBases()
    } catch (err) {
      message.error('创建失败')
    }
  }

  const handleEditBase = (base: KnowledgeBase) => {
    setEditingBase(base)
    form.setFieldsValue({ name: base.name, description: base.description, is_active: base.is_active })
    setEditModalOpen(true)
  }

  const handleSaveEdit = async (values: { name: string; description: string; is_active: boolean }) => {
    if (!editingBase) return
    try {
      await api.put(`/knowledge/bases/${editingBase.id}`, values)
      message.success('更新成功')
      setEditModalOpen(false)
      setEditingBase(null)
      form.resetFields()
      loadBases()
    } catch (err) {
      message.error('更新失败')
    }
  }

  const handleDeleteBase = async (id: number) => {
    try {
      await api.delete(`/knowledge/bases/${id}`)
      message.success('删除成功')
      if (selectedBaseId === id) {
        setSelectedBaseId(null)
      }
      loadBases()
    } catch (err) {
      message.error('删除失败')
    }
  }

  const handleUpload: UploadProps['customRequest'] = async (options) => {
    const { file, onSuccess, onError } = options as any
    if (!selectedBaseId) {
      message.error('请先选择知识库')
      return
    }
    setUploading(true)

    try {
      const formData = new FormData()
      formData.append('file', file)

      await api.post(`/knowledge/bases/${selectedBaseId}/upload`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })

      message.success(`${file.name} 上传成功`)
      onSuccess?.(null, file)
      loadDocuments()
      loadBases()
    } catch (err) {
      message.error(`${file.name} 上传失败`)
      onError?.(err as any)
    } finally {
      setUploading(false)
    }
  }

  const handleDeleteDoc = async (id: number) => {
    try {
      await api.delete(`/knowledge/documents/${id}`)
      message.success('删除成功')
      loadDocuments()
      loadBases()
    } catch (err) {
      message.error('删除失败')
    }
  }

  const columns = [
    {
      title: '文件名',
      dataIndex: 'filename',
      key: 'filename',
      render: (filename: string, record: BackendDocument) => (
        <Space>
          {fileTypeIcon(record.file_type)}
          <Text>{filename}</Text>
        </Space>
      ),
    },
    {
      title: '类型',
      dataIndex: 'file_type',
      key: 'file_type',
      width: 100,
      render: (type: string) => <Tag>{type.toUpperCase()}</Tag>,
    },
    {
      title: '大小',
      dataIndex: 'file_size',
      key: 'file_size',
      width: 100,
      render: (size: number) => formatSize(size),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => {
        const s = statusMap[status] || { color: 'default', text: status }
        return <Tag color={s.color}>{s.text}</Tag>
      },
    },
    {
      title: '切片数',
      dataIndex: 'chunk_count',
      key: 'chunk_count',
      width: 80,
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_: any, record: BackendDocument) => (
        <Popconfirm
          title="确定删除此文档？"
          onConfirm={() => handleDeleteDoc(record.id)}
        >
          <Button size="small" danger icon={<DeleteOutlined />}>
            删除
          </Button>
        </Popconfirm>
      ),
    },
  ]

  return (
    <div className={styles.container}>
      <Space direction="vertical" size="large" style={{ width: '100%' }}>
        {/* 知识库选择栏 */}
        <Card size="small">
          <Space style={{ width: '100%', justifyContent: 'space-between' }}>
            <Space>
              <DatabaseOutlined style={{ fontSize: 18, color: '#1890ff' }} />
              <Text strong style={{ fontSize: 16 }}>知识库</Text>
              <Select
                value={selectedBaseId}
                onChange={setSelectedBaseId}
                loading={loadingBases}
                style={{ minWidth: 200 }}
                placeholder="选择知识库"
                optionLabelProp="label"
              >
                {bases.map((kb) => (
                  <Option key={kb.id} value={kb.id} label={kb.name}>
                    <Space>
                      <span>{kb.name}</span>
                      <Tag color="blue" style={{ marginLeft: 8 }}>{kb.document_count} 文档</Tag>
                    </Space>
                  </Option>
                ))}
              </Select>
            </Space>
            <Space>
              <Button
                icon={<SettingOutlined />}
                onClick={() => selectedBase && handleEditBase(selectedBase)}
                disabled={!selectedBase}
              >
                编辑知识库
              </Button>
              <Popconfirm
                title="确定删除此知识库？"
                onConfirm={() => selectedBase && handleDeleteBase(selectedBase.id)}
                disabled={!selectedBase}
              >
                <Button danger disabled={!selectedBase}>删除知识库</Button>
              </Popconfirm>
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={() => {
                  form.resetFields()
                  setCreateModalOpen(true)
                }}
              >
                新建知识库
              </Button>
            </Space>
          </Space>
        </Card>

        {/* 统计卡片 */}
        {selectedBase && (
          <Row gutter={16}>
            <Col span={6}>
              <Card>
                <Statistic
                  title="文档总数"
                  value={selectedBase.document_count}
                  prefix={<FileTextOutlined />}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="知识切片"
                  value={selectedBase.chunk_count}
                  prefix={<InboxOutlined />}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="已解析"
                  value={documents.filter(d => d.status === 'completed').length}
                  suffix={`/ ${selectedBase.document_count}`}
                  valueStyle={{ color: '#52c41a' }}
                />
              </Card>
            </Col>
            <Col span={6}>
              <Card>
                <Statistic
                  title="存储占用"
                  value={parseFloat((selectedBase.total_size_bytes / (1024 * 1024)).toFixed(1))}
                  suffix=" MB"
                  precision={1}
                />
              </Card>
            </Col>
          </Row>
        )}

        {/* 上传区域 */}
        {selectedBase && (
          <Card title="上传文档">
            <Dragger
              multiple
              customRequest={handleUpload}
              accept=".pdf,.docx,.doc,.xlsx,.xls,.txt,.md,.csv,.json"
              showUploadList={false}
              disabled={uploading}
            >
              <p className="ant-upload-drag-icon">
                <InboxOutlined />
              </p>
              <p className="ant-upload-text">
                {uploading ? '上传中...' : '点击或拖拽文件到此区域上传'}
              </p>
              <p className="ant-upload-hint">
                支持 PDF、Word、Excel、TXT、Markdown、CSV、JSON 格式，上传到「{selectedBase.name}」
              </p>
            </Dragger>
          </Card>
        )}

        {/* 文档列表 */}
        {selectedBase && (
          <Card
            title="文档列表"
            extra={
              <Button icon={<SyncOutlined />} onClick={loadDocuments}>
                刷新
              </Button>
            }
          >
            <Table
              columns={columns}
              dataSource={documents}
              rowKey="id"
              loading={loadingDocs}
              pagination={{
                current: docPage,
                pageSize: docPageSize,
                total: docTotal,
                showSizeChanger: true,
                showTotal: (total) => `共 ${total} 条`,
                onChange: (page, pageSize) => {
                  setDocPage(page)
                  setDocPageSize(pageSize)
                },
              }}
            />
          </Card>
        )}

        {/* 无知识库提示 */}
        {!selectedBase && !loadingBases && (
          <Card style={{ textAlign: 'center', padding: '48px 0' }}>
            <DatabaseOutlined style={{ fontSize: 48, color: '#ccc', marginBottom: 16 }} />
            <p style={{ color: '#999', marginBottom: 16 }}>暂无知识库，请先创建一个知识库</p>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => {
                form.resetFields()
                setCreateModalOpen(true)
              }}
            >
              新建知识库
            </Button>
          </Card>
        )}
      </Space>

      {/* 创建知识库弹窗 */}
      <Modal
        title="新建知识库"
        open={createModalOpen}
        onCancel={() => setCreateModalOpen(false)}
        footer={null}
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={handleCreateBase}>
          <Form.Item
            name="name"
            label="知识库名称"
            rules={[{ required: true, message: '请输入知识库名称' }]}
          >
            <Input placeholder="请输入知识库名称" maxLength={50} />
          </Form.Item>
          <Form.Item
            name="description"
            label="描述"
          >
            <Input.TextArea placeholder="请输入知识库描述" rows={3} maxLength={200} />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0, textAlign: 'right' }}>
            <Space>
              <Button onClick={() => setCreateModalOpen(false)}>取消</Button>
              <Button type="primary" htmlType="submit">创建</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>

      {/* 编辑知识库弹窗 */}
      <Modal
        title="编辑知识库"
        open={editModalOpen}
        onCancel={() => setEditModalOpen(false)}
        footer={null}
        destroyOnClose
      >
        <Form form={form} layout="vertical" onFinish={handleSaveEdit}>
          <Form.Item
            name="name"
            label="知识库名称"
            rules={[{ required: true, message: '请输入知识库名称' }]}
          >
            <Input placeholder="请输入知识库名称" maxLength={50} />
          </Form.Item>
          <Form.Item
            name="description"
            label="描述"
          >
            <Input.TextArea placeholder="请输入知识库描述" rows={3} maxLength={200} />
          </Form.Item>
          <Form.Item
            name="is_active"
            label="是否启用"
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0, textAlign: 'right' }}>
            <Space>
              <Button onClick={() => setEditModalOpen(false)}>取消</Button>
              <Button type="primary" htmlType="submit">保存</Button>
            </Space>
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
