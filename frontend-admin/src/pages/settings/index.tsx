/**
 * 智答引擎 - 设置页面
 *
 * LLM 配置管理 + 向量化配置 + 模块开关 + 系统信息
 */

import { useState, useEffect, useCallback } from 'react'
import {
  Card, Table, Button, Modal, Form, Input, Select, Switch,
  message, Space, Divider, Tag, Typography, Alert, Row, Col, Statistic,
  Tabs, Radio, InputNumber,
} from 'antd'
import {
  PlusOutlined, EditOutlined, DeleteOutlined,
  CheckCircleOutlined, CloseCircleOutlined, GlobalOutlined,
} from '@ant-design/icons'
import { api } from '@/services/api'
import styles from './index.module.css'

const { Text } = Typography

interface ProviderTemplate {
  provider_id: string
  name: string
  category: string
  base_url: string
  default_model: string
  available_models: string[]
  requires_api_key: boolean
  api_key_label: string
}

interface LLMConfig {
  id: number
  agent_id: number | null
  provider_id: string
  provider_name: string
  base_url: string
  model_name: string
  api_key: string
  is_primary: boolean
  is_fallback: boolean
  is_active: boolean
  last_test_at: string | null
  last_test_success: boolean | null
  // 限流配置
  max_tokens_per_request: number
  max_requests_per_minute: number
  max_tokens_per_minute: number
  max_tokens_per_day: number
  tokens_used_today: number
  requests_today: number
}

interface ModuleSettings {
  enable_single_flight: boolean
  enable_graph_retrieval: boolean
  enable_rerank: boolean
  enable_streaming: boolean
  enable_auto_learning: boolean
  enable_source_citation: boolean
  enable_auto_mention: boolean
  enable_rate_limit: boolean
  enable_local_only: boolean
}

interface EmbeddingProviderModel {
  model: string
  dimension: number
}

interface EmbeddingProvider {
  provider_id: string
  name: string
  category: string
  base_url: string
  default_model: string
  default_dimension: number
  available_models: EmbeddingProviderModel[]
}

interface EmbeddingConfig {
  mode: 'local' | 'cloud'
  local_model: string
  local_device: string
  cloud_base_url: string
  cloud_api_key: string
  cloud_model: string
  cloud_dimension: number
  is_ready: boolean
  current_model: string
  current_dimension: number
}

interface WebSearchConfig { enabled: boolean; provider: string; api_key: string; max_results: number }

export default function SettingsPage() {
  const [templates, setTemplates] = useState<{
    cloud: ProviderTemplate[]
    local: ProviderTemplate[]
    custom: ProviderTemplate[]
  }>({ cloud: [], local: [], custom: [] })
  const [configs, setConfigs] = useState<LLMConfig[]>([])
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [testing, setTesting] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form] = Form.useForm()
  const [moduleSettings, setModuleSettings] = useState<ModuleSettings | null>(null)
  const [embeddingConfig, setEmbeddingConfig] = useState<EmbeddingConfig | null>(null)
  const [embeddingForm] = Form.useForm()
  const [embeddingTesting, setEmbeddingTesting] = useState(false)
  const [embeddingSaving, setEmbeddingSaving] = useState(false)
  const [embeddingProviders, setEmbeddingProviders] = useState<{
    cloud: EmbeddingProvider[]
    custom: EmbeddingProvider[]
  }>({ cloud: [], custom: [] })
  const [embeddingAvailableModels, setEmbeddingAvailableModels] = useState<EmbeddingProviderModel[]>([])
  const [embeddingProviderId, setEmbeddingProviderId] = useState<string>('')
  const [webSearchConfig, setWebSearchConfig] = useState<WebSearchConfig | null>(null)
  const [webSearchForm] = Form.useForm()
  const [webSearchSaving, setWebSearchSaving] = useState(false)

  const loadWebSearchConfig = useCallback(async () => {
    try {
      const config = await api.get<WebSearchConfig>('/admin/web-search')
      setWebSearchConfig(config)
      webSearchForm.setFieldsValue({ ...config, api_key: '' })
    } catch { message.error('加载网络检索配置失败') }
  }, [webSearchForm])

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      // 获取厂商模板（按云端/本地/自定义分组）
      const templateRes = await api.get<{
        cloud: ProviderTemplate[]
        local: ProviderTemplate[]
        custom: ProviderTemplate[]
      }>('/llm/providers')
      setTemplates(templateRes)

      // 获取 LLM 配置列表
      const configRes = await api.get<LLMConfig[]>('/llm/configs')
      setConfigs(configRes)

      // 获取模块开关设置
      const settingsRes = await api.get<ModuleSettings>('/admin/settings')
      setModuleSettings(settingsRes)

      // 获取向量化厂商列表
      const embeddingProvidersRes = await api.get<{
        cloud: EmbeddingProvider[]
        custom: EmbeddingProvider[]
      }>('/embedding/providers')
      setEmbeddingProviders(embeddingProvidersRes)

      // 获取向量化配置
      const embeddingRes = await api.get<EmbeddingConfig>('/embedding/config')
      setEmbeddingConfig(embeddingRes)
      embeddingForm.setFieldsValue({
        mode: embeddingRes.mode,
        local_model: embeddingRes.local_model,
        local_device: embeddingRes.local_device,
        cloud_base_url: embeddingRes.cloud_base_url,
        cloud_api_key: '',
        cloud_model: embeddingRes.cloud_model,
        cloud_dimension: embeddingRes.cloud_dimension,
      })
    } catch (err) {
      message.error('加载设置失败')
    } finally {
      setLoading(false)
    }
  }, [embeddingForm])

  useEffect(() => {
    loadData()
  }, [loadData])

  useEffect(() => { loadWebSearchConfig() }, [loadWebSearchConfig])

  const saveWebSearchConfig = async () => {
    const values = await webSearchForm.validateFields()
    setWebSearchSaving(true)
    try {
      const saved = await api.put<WebSearchConfig>('/admin/web-search', values)
      setWebSearchConfig(saved)
      webSearchForm.setFieldsValue({ ...saved, api_key: '' })
      message.success('网络检索配置已保存')
    } catch (error: any) { message.error(error?.response?.data?.detail || '保存失败') }
    finally { setWebSearchSaving(false) }
  }

  const handleCreate = () => {
    setEditingId(null)
    form.resetFields()
    // 单模型场景是默认使用方式，避免“测试成功但没有主模型可调用”。
    form.setFieldsValue({ is_primary: true, is_fallback: false, is_active: true })
    setModalVisible(true)
  }

  const handleEdit = (config: LLMConfig) => {
    setEditingId(config.id)
    form.setFieldsValue({
      provider_id: config.provider_id,
      provider_name: config.provider_name,
      base_url: config.base_url,
      model_name: config.model_name,
      api_key: '', // 不回显 API Key
      is_primary: config.is_primary,
      is_fallback: config.is_fallback,
      is_active: config.is_active,
    })
    setModalVisible(true)
  }

  const handleDelete = async (id: number) => {
    try {
      await api.delete(`/llm/configs/${id}`)
      message.success('删除成功')
      loadData()
    } catch (err) {
      message.error('删除失败')
    }
  }

  const handleProviderChange = async (providerId: string) => {
    try {
      const res = await api.post<{
        provider_id: string
        provider_name: string
        base_url: string
        default_model: string
        available_models: string[]
      }>('/llm/providers/autofill', { provider_id: providerId })

      form.setFieldsValue({
        provider_name: res.provider_name,
        base_url: res.base_url,
        model_name: res.default_model,
      })
    } catch (err) {
      message.error('自动填充失败')
    }
  }

  const handleEmbeddingProviderChange = async (providerId: string) => {
    setEmbeddingProviderId(providerId)
    try {
      const res = await api.post<{
        provider_id: string
        provider_name: string
        base_url: string
        default_model: string
        default_dimension: number
        available_models: EmbeddingProviderModel[]
      }>('/embedding/providers/autofill', { provider_id: providerId })

      setEmbeddingAvailableModels(res.available_models)
      embeddingForm.setFieldsValue({
        cloud_base_url: res.base_url,
        cloud_model: res.default_model,
        cloud_dimension: res.default_dimension,
      })
    } catch (err) {
      message.error('自动填充失败')
    }
  }

  const handleEmbeddingModelChange = (model: string) => {
    const modelInfo = embeddingAvailableModels.find(m => m.model === model)
    if (modelInfo) {
      embeddingForm.setFieldsValue({
        cloud_dimension: modelInfo.dimension,
      })
    }
  }

  const handleTestConnection = async () => {
    const values = form.getFieldsValue()
    if (!values.base_url || !values.model_name) {
      message.warning('请先填写 API 地址和模型名称')
      return
    }

    setTesting(true)
    try {
      const res = await api.post<{
        success: boolean
        message: string
        latency_ms: number
      }>('/llm/test-connection', {
        base_url: values.base_url,
        api_key: values.api_key,
        model_name: values.model_name,
      })

      if (res.success) {
        message.success(`连接成功！延迟 ${res.latency_ms.toFixed(0)}ms`)
      } else {
        message.error(`连接失败: ${res.message}`)
      }
    } catch (err) {
      message.error('连接测试失败')
    } finally {
      setTesting(false)
    }
  }

  const handleSubmit = async () => {
    const values = await form.validateFields()
    try {
      if (editingId) {
        await api.put(`/llm/configs/${editingId}`, values)
        message.success('更新成功')
      } else {
        await api.post('/llm/configs', values)
        message.success('创建成功')
      }
      setModalVisible(false)
      loadData()
    } catch (err) {
      message.error(editingId ? '更新失败' : '创建失败')
    }
  }

  const handleTestConfig = async (config: LLMConfig) => {
    setTesting(true)
    try {
      const res = await api.post<{
        success: boolean
        message: string
        latency_ms: number
      }>(`/llm/configs/${config.id}/test`)
      if (res.success) {
        message.success(`连接成功！延迟 ${res.latency_ms.toFixed(0)}ms`)
      } else {
        message.error(`连接失败: ${res.message}`)
      }
      loadData()
    } catch (err) {
      message.error('测试失败')
    } finally {
      setTesting(false)
    }
  }

  // 保存模块开关变更到后端
  const handleToggleModule = async (key: keyof ModuleSettings, value: boolean) => {
    // 先更新本地状态
    setModuleSettings(prev => prev ? { ...prev, [key]: value } : null)
    
    // 异步保存到后端
    try {
      await api.put('/admin/settings', {
        [key]: value
      })
    } catch (err) {
      console.error('保存模块开关失败:', err)
      message.error('保存失败，请刷新重试')
      // 回滚变更
      setModuleSettings(prev => prev ? { ...prev, [key]: !value } : null)
    }
  }

  // 向量化配置 - 测试连接
  const handleTestEmbedding = async () => {
    const values = await embeddingForm.validateFields()
    setEmbeddingTesting(true)
    try {
      const res = await api.post<{
        success: boolean
        message: string
        latency_ms: number
        dimension: number
      }>('/embedding/test', {
        mode: values.mode,
        local_model: values.local_model,
        local_device: values.local_device,
        cloud_base_url: values.cloud_base_url,
        cloud_api_key: values.cloud_api_key || undefined,
        cloud_model: values.cloud_model,
      })

      if (res.success) {
        message.success(`连接成功！延迟 ${res.latency_ms.toFixed(0)}ms，维度: ${res.dimension}`)
      } else {
        message.error(res.message || '连接失败')
      }
    } catch (err) {
      message.error('连接测试失败')
    } finally {
      setEmbeddingTesting(false)
    }
  }

  // 向量化配置 - 保存
  const handleSaveEmbedding = async () => {
    const values = await embeddingForm.validateFields()
    setEmbeddingSaving(true)
    try {
      const body: Partial<EmbeddingConfig> = {
        mode: values.mode,
        local_model: values.local_model,
        local_device: values.local_device,
        cloud_base_url: values.cloud_base_url,
        cloud_model: values.cloud_model,
        cloud_dimension: values.cloud_dimension,
      }
      if (values.cloud_api_key) {
        body.cloud_api_key = values.cloud_api_key
      }

      const res = await api.put<EmbeddingConfig>('/embedding/config', body)
      setEmbeddingConfig(res)
      message.success('保存成功')
    } catch (err) {
      message.error('保存失败')
    } finally {
      setEmbeddingSaving(false)
    }
  }

  const columns = [
    {
      title: '厂商',
      dataIndex: 'provider_name',
      key: 'provider_name',
      render: (text: string, record: LLMConfig) => (
        <Space>
          {text}
          {record.is_primary && <Tag color="blue">主模型</Tag>}
          {record.is_fallback && <Tag color="orange">降级</Tag>}
        </Space>
      ),
    },
    {
      title: '模型',
      dataIndex: 'model_name',
      key: 'model_name',
    },
    {
      title: '状态',
      dataIndex: 'is_active',
      key: 'is_active',
      render: (active: boolean) => (
        active
          ? <Tag icon={<CheckCircleOutlined />} color="success">启用</Tag>
          : <Tag icon={<CloseCircleOutlined />} color="default">禁用</Tag>
      ),
    },
    {
      title: '测试',
      dataIndex: 'last_test_success',
      key: 'last_test_success',
      render: (success: boolean | null) => {
        if (success === null) return <Text type="secondary">未测试</Text>
        return success
          ? <CheckCircleOutlined style={{ color: '#52c41a' }} />
          : <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
      },
    },
    {
      title: '今日用量',
      key: 'usage',
      render: (_: any, record: LLMConfig) => (
        <Text type="secondary">
          {record.requests_today || 0}次 / {record.tokens_used_today || 0}tokens
        </Text>
      ),
    },
    {
      title: '操作',
      key: 'action',
      render: (_: any, record: LLMConfig) => (
        <Space size="middle">
          <Button
            size="small"
            icon={<GlobalOutlined />}
            onClick={() => handleTestConfig(record)}
            loading={testing}
          >
            测试
          </Button>
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => handleEdit(record)}
          >
            编辑
          </Button>
          <Button
            size="small"
            danger
            icon={<DeleteOutlined />}
            onClick={() => handleDelete(record.id)}
          >
            删除
          </Button>
        </Space>
      ),
    },
  ]

  const tabItems = [
    {
      key: 'llm',
      label: 'LLM 配置',
      children: (
        <Card
          extra={
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={handleCreate}
            >
              新增配置
            </Button>
          }
        >
          <Alert
            message="配置说明"
            description="选择厂商后会自动填充 API 地址，只需输入 API Key 即可。支持多个配置（一个主模型 + 一个降级模型）。"
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
          />

          <Table
            columns={columns}
            dataSource={configs}
            rowKey="id"
            loading={loading}
            pagination={false}
          />
        </Card>
      ),
    },
    {
      key: 'embedding',
      label: '向量化配置',
      children: (
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          {embeddingConfig && (
            <Card>
              <Row gutter={16}>
                <Col span={8}>
                  <Statistic
                    title="就绪状态"
                    value={embeddingConfig.is_ready ? '就绪' : '未就绪'}
                    valueStyle={{ color: embeddingConfig.is_ready ? '#3f8600' : '#cf1322' }}
                  />
                </Col>
                <Col span={8}>
                  <Statistic title="当前模型" value={embeddingConfig.current_model || '-'} />
                </Col>
                <Col span={8}>
                  <Statistic title="当前维度" value={embeddingConfig.current_dimension || 0} />
                </Col>
              </Row>
            </Card>
          )}

          <Card title="配置">
            <Form form={embeddingForm} layout="vertical">
              <Form.Item
                name="mode"
                label="模式"
                rules={[{ required: true, message: '请选择模式' }]}
              >
                <Radio.Group>
                  <Radio value="local">本地模型</Radio>
                  <Radio value="cloud">云端 API</Radio>
                </Radio.Group>
              </Form.Item>

              <Form.Item
                noStyle
                shouldUpdate={(prev, cur) => prev.mode !== cur.mode}
              >
                {({ getFieldValue }) => {
                  const mode = getFieldValue('mode')
                  if (mode === 'local') {
                    return (
                      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                        <Form.Item
                          name="local_model"
                          label="模型名称"
                          rules={[{ required: true, message: '请输入模型名称' }]}
                        >
                          <Input placeholder="例如: BAAI/bge-large-zh-v1.5" />
                        </Form.Item>
                        <Form.Item
                          name="local_device"
                          label="运行设备"
                          rules={[{ required: true, message: '请选择运行设备' }]}
                        >
                          <Select>
                            <Select.Option value="cpu">CPU</Select.Option>
                            <Select.Option value="cuda">CUDA</Select.Option>
                          </Select>
                        </Form.Item>
                      </Space>
                    )
                  }
                  return (
                    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
                      <Form.Item
                        label="厂商"
                        rules={[{ required: true, message: '请选择厂商' }]}
                      >
                        <Select
                          placeholder="选择厂商"
                          value={embeddingProviderId || undefined}
                          onChange={handleEmbeddingProviderChange}
                          showSearch
                          optionFilterProp="label"
                          options={[
                            {
                              label: '云端厂商',
                              options: embeddingProviders.cloud.map(p => ({
                                label: p.name,
                                value: p.provider_id,
                              })),
                            },
                            {
                              label: '自定义',
                              options: embeddingProviders.custom.map(p => ({
                                label: p.name,
                                value: p.provider_id,
                              })),
                            },
                          ]}
                        />
                      </Form.Item>
                      <Form.Item
                        name="cloud_base_url"
                        label="API 基础地址"
                        rules={[{ required: true, message: '请输入 API 基础地址' }]}
                      >
                        <Input placeholder="例如: https://api.openai.com/v1" />
                      </Form.Item>
                      <Form.Item
                        name="cloud_api_key"
                        label="API Key"
                        extra={embeddingConfig?.cloud_api_key ? `当前: ${embeddingConfig.cloud_api_key}` : ''}
                      >
                        <Input.Password placeholder="留空表示不修改" autoComplete="new-password" />
                      </Form.Item>
                      <Form.Item
                        name="cloud_model"
                        label="模型名称"
                        rules={[{ required: true, message: '请选择或输入模型名称' }]}
                      >
                        {embeddingAvailableModels.length > 0 ? (
                          <Select
                            placeholder="选择模型"
                            onChange={handleEmbeddingModelChange}
                            options={embeddingAvailableModels.map(m => ({
                              label: `${m.model} (${m.dimension}维)`,
                              value: m.model,
                            }))}
                          />
                        ) : (
                          <Input placeholder="例如: text-embedding-3-small" />
                        )}
                      </Form.Item>
                      <Form.Item
                        name="cloud_dimension"
                        label="向量维度"
                        rules={[{ required: true, message: '请输入向量维度' }]}
                      >
                        <InputNumber min={1} style={{ width: '100%' }} placeholder="例如: 1536" />
                      </Form.Item>
                    </Space>
                  )
                }}
              </Form.Item>

              <Divider />

              <Form.Item>
                <Space>
                  <Button onClick={handleTestEmbedding} loading={embeddingTesting}>
                    测试连接
                  </Button>
                  <Button type="primary" onClick={handleSaveEmbedding} loading={embeddingSaving}>
                    保存配置
                  </Button>
                </Space>
              </Form.Item>
            </Form>
          </Card>
        </Space>
      ),
    },
    {
      key: 'web-search',
      label: '网络检索',
      children: (
        <Card title="网络检索补充">
          <Alert type="info" showIcon style={{ marginBottom: 20 }} message="仅在知识库未命中时调用网络检索；网络内容会作为补充来源，不会覆盖知识库结论。" />
          <Form form={webSearchForm} layout="vertical" style={{ maxWidth: 620 }}>
            <Form.Item name="enabled" label="启用网络检索" valuePropName="checked"><Switch /></Form.Item>
            <Form.Item name="provider" label="搜索服务" rules={[{ required: true }]}><Select options={[{ label: 'Tavily（推荐，有免费额度）', value: 'tavily' }, { label: 'Bing RSS（实验，无需密钥）', value: 'bing_rss' }]} /></Form.Item>
            <Form.Item name="api_key" label="搜索 API Key" extra={webSearchConfig?.api_key ? `当前：${webSearchConfig.api_key}；留空表示不修改` : 'Tavily 需要 API Key；Bing RSS 实验模式无需填写'}><Input.Password autoComplete="new-password" placeholder="Bing RSS 可留空" /></Form.Item>
            <Form.Item name="max_results" label="每次最多返回结果" rules={[{ required: true }]}><InputNumber min={1} max={10} style={{ width: '100%' }} /></Form.Item>
            <Button type="primary" onClick={saveWebSearchConfig} loading={webSearchSaving}>保存网络检索配置</Button>
          </Form>
        </Card>
      ),
    },
    {
      key: 'modules',
      label: '功能开关',
      children: (
        <Card>
          <Row gutter={[16, 16]}>
            {moduleSettings && Object.entries(moduleSettings).map(([key, value]) => (
              <Col xs={24} sm={12} key={key}>
                <Card size="small" bordered>
                  <Space>
                    <Switch
                      checked={value}
                      onChange={(checked) => handleToggleModule(key as keyof ModuleSettings, checked)}
                    />
                    <div>
                      <Text strong>{
                        {
                          enable_single_flight: '幂等 Single-Flight',
                          enable_graph_retrieval: '图检索增强',
                          enable_rerank: '重排序',
                          enable_streaming: '流式输出',
                          enable_auto_learning: '自动学习',
                          enable_source_citation: '返回结构化来源',
                          enable_auto_mention: '自动 @ 指定用户',
                          enable_rate_limit: '请求限流',
                          enable_local_only: '仅本地访问',
                        }[key]
                      }</Text>
                    </div>
                  </Space>
                </Card>
              </Col>
            ))}
          </Row>
        </Card>
      ),
    },
    {
      key: 'system',
      label: '系统信息',
      children: (
        <Space direction="vertical" size="large" style={{ width: '100%' }}>
          <Card title="系统资源">
            <Row gutter={16}>
              <Col span={8}>
                <Statistic title="内存 (GB)" value={4} />
              </Col>
              <Col span={8}>
                <Statistic title="CPU 核心" value={8} />
              </Col>
              <Col span={8}>
                <Statistic title="配置方案" value={0} formatter={() => 'balanced'} />
              </Col>
            </Row>
          </Card>

          <Card title="安全信息">
            <Alert
              message="本地安全"
              description={
                <ul>
                  <li>API Key 使用 AES-256-GCM 加密存储，密钥派生自机器指纹</li>
                  <li>所有数据都存储在本地目录，不上传到任何云端</li>
                  <li>仅允许 127.0.0.1 访问 API，防止外部网络访问</li>
                  <li>每个 Agent 运行在独立沙箱，限制文件系统访问</li>
                </ul>
              }
              type="success"
              showIcon
            />
          </Card>
        </Space>
      ),
    },
  ]

  return (
    <div className={styles.container}>
      <Tabs
        defaultActiveKey="llm"
        items={tabItems}
        size="large"
      />

      {/* 新建/编辑 模态框 */}
      <Modal
        title={editingId ? '编辑 LLM 配置' : '新建 LLM 配置'}
        open={modalVisible}
        onCancel={() => setModalVisible(false)}
        onOk={handleSubmit}
        okText={editingId ? '保存' : '创建'}
        width={600}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="provider_id"
            label="厂商"
            rules={[{ required: true, message: '请选择厂商' }]}
          >
            <Select
              placeholder="选择厂商"
              onChange={handleProviderChange}
              showSearch
              optionFilterProp="label"
              options={[
                {
                  label: '云端',
                  options: templates.cloud.map(p => ({
                    label: p.name,
                    value: p.provider_id,
                  })),
                },
                {
                  label: '本地',
                  options: templates.local.map(p => ({
                    label: p.name,
                    value: p.provider_id,
                  })),
                },
                {
                  label: '自定义',
                  options: templates.custom.map(p => ({
                    label: p.name,
                    value: p.provider_id,
                  })),
                },
              ]}
            />
          </Form.Item>

          <Form.Item
            name="provider_name"
            label="厂商名称"
            rules={[{ required: true, message: '请输入厂商名称' }]}
          >
            <Input placeholder="例如: DeepSeek" />
          </Form.Item>

          <Form.Item
            name="base_url"
            label="API 地址"
            rules={[{ required: true, message: '请输入 API 基础地址' }]}
          >
            <Input placeholder="例如: https://api.deepseek.com" />
          </Form.Item>

          <Form.Item
            name="model_name"
            label="模型名称"
            rules={[{ required: true, message: '请输入模型名称' }]}
          >
            <Input placeholder="例如: deepseek-v4-pro" />
          </Form.Item>

          <Form.Item
            name="api_key"
            label="API Key"
            extra={editingId ? '留空表示不修改原有 API Key' : ''}
          >
            <Input.Password placeholder="请输入 API Key" autoComplete="new-password" />
          </Form.Item>

          <Form.Item>
            <Space>
              <Button onClick={handleTestConnection} loading={testing}>
                测试连接
              </Button>
            </Space>
          </Form.Item>

          <Divider />

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="is_primary" valuePropName="checked" label="主模型">
                <Switch />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="is_fallback" valuePropName="checked" label="降级模型">
                <Switch />
              </Form.Item>
            </Col>
          </Row>

          <Form.Item name="is_active" valuePropName="checked" label="启用" initialValue={true}>
            <Switch defaultChecked />
          </Form.Item>

          <Divider>API 限流配置</Divider>

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="max_tokens_per_request"
                label="单次请求 Token 上限"
                initialValue={4096}
              >
                <Input type="number" addonAfter="tokens" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="max_requests_per_minute"
                label="每分钟请求上限"
                initialValue={30}
              >
                <Input type="number" addonAfter="次/分" />
              </Form.Item>
            </Col>
          </Row>

          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name="max_tokens_per_minute"
                label="每分钟 Token 上限"
                initialValue={100000}
              >
                <Input type="number" addonAfter="tokens/分" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="max_tokens_per_day"
                label="每日 Token 上限"
                initialValue={1000000}
              >
                <Input type="number" addonAfter="tokens/天" />
              </Form.Item>
            </Col>
          </Row>

          <Divider />

          <Form.Item
            name="agent_id"
            label="Agent ID"
            extra="留空表示全局配置，所有 Agent 共享"
          >
            <Input type="number" placeholder="全局配置留空" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
