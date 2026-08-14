/**
 * 智答引擎 - 设置页面
 *
 * LLM 配置管理 + 网络检索 + 模块开关 + 系统信息
 */

import { useState, useEffect, useCallback } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Card, Button, Modal, Form, Input, Select, Switch,
  message, Space, Divider, Tag, Typography, Alert, Row, Col, Statistic,
  InputNumber,
} from 'antd'
import {
  PlusOutlined, EditOutlined, DeleteOutlined,
  ArrowLeftOutlined,
} from '@ant-design/icons'
import { api } from '@/services/api'
import styles from './index.module.css'

const { Title, Text } = Typography

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
  is_context_model: boolean
  context_rewrite_timeout_seconds: number
  context_compaction_timeout_seconds: number
  is_active: boolean
  last_test_at: string | null
  last_test_success: boolean | null
  // 限流配置
  max_tokens_per_request: number
  max_requests_per_minute: number
  max_tokens_per_minute: number
  max_tokens_per_day: number
}

interface ModuleSettings {
  enable_source_citation: boolean
  enable_rate_limit: boolean
  development_mode: boolean
}

interface WebSearchConfig { enabled: boolean; provider: string; tavily_api_key: string; exa_api_key: string; tavily_configured: boolean; exa_configured: boolean; max_results: number }
type WebSearchHealth = { success: boolean; message: string }
interface ObservabilityConfig {
  langfuse_enabled: boolean; langfuse_host: string; langfuse_public_key: string; langfuse_secret_key: string
  public_key_configured: boolean; secret_key_configured: boolean; online_evaluation_enabled: boolean; last_test_success: boolean | null; last_test_at: string | null; last_test_message: string | null
}

const SEARCH_PROVIDERS = [
  { id: 'tavily', name: 'Tavily', description: '面向 AI 的网页搜索与摘要', keyRequired: true },
  { id: 'exa', name: 'Exa', description: '语义搜索与网页正文提取', keyRequired: true },
  { id: 'duckduckgo', name: 'DuckDuckGo', description: '免费实验搜索，无需密钥', keyRequired: false },
  { id: 'bing_rss', name: 'Bing RSS', description: '免费 RSS 降级通道，无需密钥', keyRequired: false },
]
export default function SettingsPage() {
  const { section, provider } = useParams()
  const navigate = useNavigate()
  const [templates, setTemplates] = useState<{
    cloud: ProviderTemplate[]
    custom: ProviderTemplate[]
  }>({ cloud: [], custom: [] })
  const [configs, setConfigs] = useState<LLMConfig[]>([])
  const [loading, setLoading] = useState(false)
  const [modalVisible, setModalVisible] = useState(false)
  const [testing, setTesting] = useState(false)
  const [configTestingId, setConfigTestingId] = useState<number | null>(null)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [form] = Form.useForm()
  const [moduleSettings, setModuleSettings] = useState<ModuleSettings | null>(null)
  const [webSearchConfig, setWebSearchConfig] = useState<WebSearchConfig | null>(null)
  const [webSearchForm] = Form.useForm()
  const [webSearchSaving, setWebSearchSaving] = useState(false)
  const [webSearchTestingProvider, setWebSearchTestingProvider] = useState<string | null>(null)
  const [webSearchModalOpen, setWebSearchModalOpen] = useState(false)
  const [webSearchEditingProvider, setWebSearchEditingProvider] = useState('tavily')
  const [webSearchHealth, setWebSearchHealth] = useState<Record<string, WebSearchHealth>>({})
  const [observabilityConfig, setObservabilityConfig] = useState<ObservabilityConfig | null>(null)
  const [observabilityForm] = Form.useForm()
  const [observabilitySaving, setObservabilitySaving] = useState(false)
  const [observabilityTesting, setObservabilityTesting] = useState(false)
  const [observabilityModalOpen, setObservabilityModalOpen] = useState(false)

  const loadWebSearchConfig = useCallback(async () => {
    try {
      const config = await api.get<WebSearchConfig>('/admin/web-search')
      setWebSearchConfig(config)
    } catch { message.error('加载网络检索配置失败') }
  }, [])

  const loadObservabilityConfig = useCallback(async () => {
    try {
      const config = await api.get<ObservabilityConfig>('/admin/observability')
      setObservabilityConfig(config)
      observabilityForm.setFieldsValue({ ...config, langfuse_public_key: '', langfuse_secret_key: '' })
    } catch { message.error('加载可观测配置失败') }
  }, [observabilityForm])

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      // 获取厂商模板（按云端/本地/自定义分组）
      const templateRes = await api.get<{
        cloud: ProviderTemplate[]
        custom: ProviderTemplate[]
      }>('/llm/providers')
      setTemplates(templateRes)

      // 获取 LLM 配置列表
      const configRes = await api.get<LLMConfig[]>('/llm/configs')
      setConfigs(configRes)

      // 获取模块开关设置
      const settingsRes = await api.get<ModuleSettings>('/admin/settings')
      setModuleSettings(settingsRes)

    } catch (err) {
      message.error('加载设置失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData()
  }, [loadData])

  useEffect(() => { loadWebSearchConfig() }, [loadWebSearchConfig])
  useEffect(() => { loadObservabilityConfig() }, [loadObservabilityConfig])
  useEffect(() => {
    if (section === 'observability' && provider === 'langfuse') setObservabilityModalOpen(true)
  }, [section, provider])

  const saveObservabilityConfig = async () => {
    const values = await observabilityForm.validateFields()
    setObservabilitySaving(true)
    try {
      const saved = await api.put<ObservabilityConfig>('/admin/observability', values)
      setObservabilityConfig(saved)
      observabilityForm.setFieldsValue({ ...saved, langfuse_public_key: '', langfuse_secret_key: '' })
      message.success('Langfuse 可观测配置已保存')
      setObservabilityModalOpen(false)
      navigate('/settings/observability')
    } catch (error: any) { message.error(error?.response?.data?.detail || '保存失败') }
    finally { setObservabilitySaving(false) }
  }

  const testObservabilityConfig = async () => {
    setObservabilityTesting(true)
    try {
      const result = await api.post<{ success: boolean; message: string }>('/admin/observability/test')
      message[result.success ? 'success' : 'error'](result.message)
      await loadObservabilityConfig()
    } catch (error: any) { message.error(error?.response?.data?.detail || '连接测试失败') }
    finally { setObservabilityTesting(false) }
  }

  const toggleObservabilityConfig = async () => {
    if (!observabilityConfig) return
    const enabled = !observabilityConfig.langfuse_enabled
    setObservabilitySaving(true)
    try {
      const saved = await api.put<ObservabilityConfig>('/admin/observability', {
        langfuse_enabled: enabled,
        langfuse_host: observabilityConfig.langfuse_host,
      })
      setObservabilityConfig(saved)
      observabilityForm.setFieldsValue({ ...saved, langfuse_public_key: '', langfuse_secret_key: '' })
      message.success(enabled ? '观测平台已启用' : '观测平台已停用')
    } catch (error: any) { message.error(error?.response?.data?.detail || '更新状态失败') }
    finally { setObservabilitySaving(false) }
  }

  const deleteObservabilityConfig = () => {
    Modal.confirm({
      title: '删除观测平台配置？',
      content: '将删除本地保存的 Host、密钥和自动评测配置，并立即停止上报。此操作不可恢复。',
      okText: '删除', okButtonProps: { danger: true }, cancelText: '取消',
      onOk: async () => {
        try {
          await api.delete('/admin/observability')
          await loadObservabilityConfig()
          message.success('观测平台配置已删除')
        } catch (error: any) { message.error(error?.response?.data?.detail || '删除失败') }
      },
    })
  }

  const saveWebSearchConfig = async () => {
    const values = await webSearchForm.validateFields()
    const provider = webSearchEditingProvider
    const payload = {
      ...values,
      provider,
      enabled: Boolean(webSearchConfig?.enabled && webSearchConfig.provider === provider),
    }
    setWebSearchSaving(true)
    try {
      const saved = await api.put<WebSearchConfig>('/admin/web-search', payload)
      const configured = provider === 'exa' ? saved.exa_configured : saved.tavily_configured
      const submittedKey = provider === 'exa' ? values.exa_api_key : values.tavily_api_key
      if (submittedKey && configured !== true) {
        message.error('密钥没有写入数据库，请重启后端加载最新接口后重新保存')
        return
      }
      setWebSearchConfig(saved)
      setWebSearchModalOpen(false)
      await loadWebSearchConfig()
      message.success('网络检索配置已保存')
    } catch (error: any) { message.error(error?.response?.data?.detail || '保存失败') }
    finally { setWebSearchSaving(false) }
  }

  const testWebSearchProvider = async (provider: string, draftValues?: Record<string, any>) => {
    const apiKey = provider === 'exa' ? draftValues?.exa_api_key : draftValues?.tavily_api_key
    const hasSavedKey = provider === 'exa' ? webSearchConfig?.exa_configured : webSearchConfig?.tavily_configured
    if ((provider === 'tavily' || provider === 'exa') && !apiKey && !hasSavedKey) {
      const tip = `请先配置 ${provider === 'exa' ? 'Exa' : 'Tavily'} API Key，再测试连接`
      setWebSearchHealth(current => ({ ...current, [provider]: { success: false, message: tip } }))
      message.warning(tip)
      return
    }
    if (webSearchTestingProvider) return
    setWebSearchTestingProvider(provider)
    try {
      const result = await api.post<{ success: boolean; message: string; provider: string; result_count: number }>('/admin/web-search/test', {
        provider, api_key: apiKey, max_results: draftValues?.max_results || webSearchConfig?.max_results || 3,
      })
      if (result.provider && result.provider !== provider) throw new Error(`测试链路不一致：请求 ${provider}，返回 ${result.provider}`)
      const resultMessage = result.success ? `${result.message}，返回 ${result.result_count} 条结果` : result.message
      setWebSearchHealth(current => ({ ...current, [provider]: { success: result.success, message: resultMessage } }))
      if (result.success) message.success(resultMessage)
      else message.error(resultMessage)
    } catch (error: any) {
      const resultMessage = error?.response?.data?.detail || error?.message || '网络检索测试失败'
      setWebSearchHealth(current => ({ ...current, [provider]: { success: false, message: resultMessage } }))
      message.error(resultMessage)
    }
    finally { setWebSearchTestingProvider(null) }
  }

  const testWebSearchConfig = async () => {
    const values = await webSearchForm.validateFields()
    await testWebSearchProvider(webSearchEditingProvider, values)
  }

  const openWebSearchConfig = (provider: string) => {
    setWebSearchEditingProvider(provider)
    webSearchForm.resetFields()
    webSearchForm.setFieldsValue({
      max_results: webSearchConfig?.max_results || 3,
      tavily_api_key: '',
      exa_api_key: '',
    })
    setWebSearchModalOpen(true)
  }

  const toggleWebSearchProvider = async (provider: string) => {
    const isCurrentProvider = webSearchConfig?.enabled && webSearchConfig.provider === provider
    const requiresKey = provider === 'tavily' || provider === 'exa'
    const hasSavedKey = provider === 'exa' ? webSearchConfig?.exa_configured : webSearchConfig?.tavily_configured
    if (!isCurrentProvider && requiresKey && !hasSavedKey) {
      message.warning(`请先配置 ${provider === 'exa' ? 'Exa' : 'Tavily'} API Key`)
      return
    }
    try {
      const saved = await api.put<WebSearchConfig>('/admin/web-search', {
        enabled: !isCurrentProvider,
        provider,
        max_results: webSearchConfig?.max_results || 3,
      })
      setWebSearchConfig(saved)
      message.success(!isCurrentProvider ? `${provider === 'bing_rss' ? 'Bing RSS' : provider === 'duckduckgo' ? 'DuckDuckGo' : provider === 'exa' ? 'Exa' : 'Tavily'} 已启用` : '网络检索已停用')
    } catch (error: any) { message.error(error?.response?.data?.detail || '更新网络检索状态失败') }
  }

  const handleCreate = () => {
    setEditingId(null)
    form.resetFields()
    // 单模型场景是默认使用方式，避免“测试成功但没有主模型可调用”。
    form.setFieldsValue({ role: 'primary', is_active: true, context_rewrite_timeout_seconds: 10, context_compaction_timeout_seconds: 25 })
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
      role: config.is_primary ? 'primary' : config.is_fallback ? 'fallback' : config.is_context_model ? 'context' : 'standalone',
      is_active: config.is_active,
      agent_id: config.agent_id,
      max_tokens_per_request: config.max_tokens_per_request,
      max_requests_per_minute: config.max_requests_per_minute,
      max_tokens_per_minute: config.max_tokens_per_minute,
      max_tokens_per_day: config.max_tokens_per_day,
      context_rewrite_timeout_seconds: config.context_rewrite_timeout_seconds,
      context_compaction_timeout_seconds: config.context_compaction_timeout_seconds,
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

  const handleTestConnection = async () => {
    const values = form.getFieldsValue()
    if (!values.base_url || !values.model_name) {
      message.warning('请先填写 API 地址和模型名称')
      return
    }

    setTesting(true)
    try {
      if (editingId && !values.api_key) {
        const res = await api.post<{
          success: boolean
          message: string
          latency_ms: number
        }>(`/llm/configs/${editingId}/test`)
        if (res.success) message.success(`连接成功！${Number.isFinite(res.latency_ms) ? `延迟 ${res.latency_ms.toFixed(0)}ms` : ''}`)
        else message.error(`连接失败: ${res.message}`)
        return
      }
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
        message.success(`连接成功！${Number.isFinite(res.latency_ms) ? `延迟 ${res.latency_ms.toFixed(0)}ms` : ''}`)
      } else {
        message.error(`连接失败: ${res.message}`)
      }
    } catch (err) {
      const detail = (err as any)?.response?.data?.detail || (err as any)?.message || '连接测试失败'
      message.error(detail)
    } finally {
      setTesting(false)
    }
  }

  const handleSubmit = async () => {
    const values = await form.validateFields()
    const payload = {
      ...values,
      is_primary: values.role === 'primary',
      is_fallback: values.role === 'fallback',
      is_context_model: values.role === 'context',
    }
    // 独立模型只保存配置，不在创建时进入任何调用链路；需要时再从列表显式启用。
    if (!editingId && values.role === 'standalone') payload.is_active = false
    delete payload.role
    try {
      if (editingId) {
        await api.put(`/llm/configs/${editingId}`, payload)
        message.success('更新成功')
      } else {
        await api.post('/llm/configs', payload)
        message.success('创建成功')
      }
      setModalVisible(false)
      loadData()
    } catch (err) {
      message.error(editingId ? '更新失败' : '创建失败')
    }
  }

  const handleTestConfig = async (config: LLMConfig) => {
    // 配置卡片的测试是单模型直连，不走主/降级调用链；按配置 ID 记录状态，
    // 防止测试降级模型时主模型卡片也显示为“测试中”。
    setConfigTestingId(config.id)
    try {
      const res = await api.post<{
        success: boolean
        message: string
        latency_ms: number
      }>(`/llm/configs/${config.id}/test`)
      if (res.success) {
        message.success(`连接成功！${Number.isFinite(res.latency_ms) ? `延迟 ${res.latency_ms.toFixed(0)}ms` : ''}`)
      } else {
        message.error(`连接失败: ${res.message}`)
      }
      loadData()
    } catch (err: any) {
      message.error(err?.response?.data?.detail || err?.message || '测试失败')
    } finally {
      setConfigTestingId(null)
    }
  }

  const toggleLLMConfig = async (config: LLMConfig) => {
    try {
      await api.put(`/llm/configs/${config.id}`, { is_active: !config.is_active })
      await loadData()
      message.success(config.is_active ? '模型已停用' : '模型已启用')
    } catch (error: any) { message.error(error?.response?.data?.detail || '更新模型状态失败') }
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

  const tabItems = [
    {
      key: 'llm',
      label: 'LLM 配置',
      children: <div className="web-search-settings"><Alert message="主模型与降级链路" description="主模型调用失败后，会按已启用的降级配置继续尝试。独立模型创建后默认停用；如需用于评测等独立用途，请在保存后手动启用。" type="info" showIcon />
        <div className="web-search-provider-list">{configs.map(config => <Card key={config.id} size="small" loading={loading} className={`web-search-provider-card ${config.is_active ? 'is-active' : ''}`}><div className="web-search-provider-main"><div><Space><Text strong>{config.provider_name}</Text>{config.is_primary && <Tag color="blue">主模型</Tag>}{config.is_fallback && <Tag color="orange">降级</Tag>}{config.is_context_model && <Tag color="purple">重写 / 压缩</Tag>}</Space><Text type="secondary">{config.model_name}</Text></div><div className="web-search-provider-status"><Tag className={config.is_active ? 'search-chain-active' : undefined} color={config.is_active ? 'success' : 'default'}>{config.is_active ? '已启用' : '已停用'}</Tag><Text type={config.last_test_success === false ? 'danger' : 'secondary'}>{config.last_test_success === true ? '可用' : config.last_test_success === false ? '不可用' : '待检测'}</Text></div></div><Space wrap className="web-search-provider-actions"><Button onClick={() => handleTestConfig(config)} loading={configTestingId === config.id}>测试连接</Button><Button icon={<EditOutlined />} onClick={() => handleEdit(config)}>配置</Button><Button type={config.is_active ? 'default' : 'primary'} onClick={() => toggleLLMConfig(config)}>{config.is_active ? '停用' : '启用'}</Button><Button danger icon={<DeleteOutlined />} disabled={config.is_primary} onClick={() => handleDelete(config.id)}>删除</Button></Space></Card>)}</div>
      </div>,
    },
    {
      key: 'web-search',
      label: '网络检索',
      children: (
        <div className="web-search-settings">
          <Alert type="info" showIcon message="仅在本地知识存在信息缺口时补充网络检索；网络内容只作为补充来源，不会覆盖知识库结论。" />
          <div className="web-search-provider-list">
            {SEARCH_PROVIDERS.map(item => {
              const active = webSearchConfig?.enabled && webSearchConfig.provider === item.id
              const health = webSearchHealth[item.id]
              const configured = !item.keyRequired || Boolean(item.id === 'exa' ? webSearchConfig?.exa_configured : webSearchConfig?.tavily_configured)
              const status = health
                ? health
                : active ? { success: false, message: '已启用，待检测' }
                : { success: false, message: configured ? '已配置，未启用' : '未配置' }
              return <Card key={item.id} size="small" className={`web-search-provider-card ${active ? 'is-active' : ''}`}>
                <div className="web-search-provider-main">
                  <div><Text strong>{item.name}</Text><Text type="secondary">{item.description}</Text></div>
                  <div className="web-search-provider-status"><Tag className={active ? 'search-chain-active' : undefined} color={active ? 'success' : 'default'}>{active ? '已启用' : '备用'}</Tag><Text type={health && !health.success ? 'danger' : 'secondary'}>{health ? (health.success ? '可用' : '不可用') : status.message}</Text></div>
                </div>
                <Text className="web-search-health-copy" type="secondary">{health?.message || (active ? '尚未测试该搜索链路' : status.message)}</Text>
                <Space wrap className="web-search-provider-actions">
                  <Button onClick={() => testWebSearchProvider(item.id)} loading={webSearchTestingProvider === item.id} disabled={Boolean(webSearchTestingProvider && webSearchTestingProvider !== item.id)}>测试连接</Button>
                  <Button onClick={() => openWebSearchConfig(item.id)} disabled={Boolean(webSearchTestingProvider)}>配置</Button>
                  <Button type={active ? 'default' : 'primary'} onClick={() => toggleWebSearchProvider(item.id)} disabled={Boolean(webSearchTestingProvider)}>{active ? '停用' : '启用'}</Button>
                </Space>
              </Card>
            })}
          </div>
        </div>
      ),
    },
    {
      key: 'observability',
      label: 'Agent 链路观测',
      children: <div className="web-search-settings">
        <Alert type="info" showIcon message="Agent 链路观测" description="启用后会向配置的 HTTPS Langfuse 地址完整上报用户问题、模型回答、检索知识片段、用户标识及性能数据。上报失败不会影响用户回答；密钥仅加密保存在本地。保存配置后，数据库配置优先于部署环境变量；未保存时才使用环境变量初始值。" />
        <Card size="small" className={`web-search-provider-card observability-provider-card ${observabilityConfig?.langfuse_enabled ? 'is-active' : ''}`} style={{ marginTop: 16 }}>
          <div className="web-search-provider-main"><div><Text strong>Langfuse</Text><Text type="secondary">记录完整 Agent Trace、检索证据和模型调用{observabilityConfig?.online_evaluation_enabled ? '；已提供在线 Judge 评分上下文' : ''}</Text></div><div className="web-search-provider-status"><Tag className={observabilityConfig?.langfuse_enabled ? 'search-chain-active' : undefined} color={observabilityConfig?.langfuse_enabled ? 'success' : 'default'}>{observabilityConfig?.langfuse_enabled ? '正在上报' : '未启用'}</Tag><Text type={observabilityConfig?.last_test_success === false ? 'danger' : 'secondary'}>{observabilityConfig?.last_test_success === true ? '连接正常' : observabilityConfig?.last_test_success === false ? '连接异常' : '待检测'}</Text></div></div>
          <Text className="web-search-health-copy" type="secondary">{observabilityConfig?.last_test_message || '配置完成后可测试 Langfuse 项目连接'}</Text>
          <Space wrap className="web-search-provider-actions"><Button onClick={() => setObservabilityModalOpen(true)}>配置</Button><Button onClick={testObservabilityConfig} loading={observabilityTesting} disabled={!observabilityConfig?.public_key_configured || !observabilityConfig?.secret_key_configured}>测试连接</Button><Button type={observabilityConfig?.langfuse_enabled ? 'default' : 'primary'} onClick={toggleObservabilityConfig} loading={observabilitySaving}>{observabilityConfig?.langfuse_enabled ? '停用' : '启用'}</Button><Button danger icon={<DeleteOutlined />} onClick={deleteObservabilityConfig} disabled={!observabilityConfig?.public_key_configured && !observabilityConfig?.secret_key_configured}>删除</Button></Space>
        </Card>
      </div>,
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
                          enable_source_citation: '返回结构化来源',
                          enable_rate_limit: '请求限流',
                          development_mode: '开发维护模式（暂停用户端问答）',
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
  const tabKey = ({ models: 'llm', search: 'web-search', observability: 'observability', runtime: 'system' }[section || ''] || 'llm')
  const activeItem = tabItems.find(item => item.key === tabKey)

  const backPath = tabKey === 'observability' && provider ? '/settings/observability' : '/settings'
  return (
    <div className={styles.container}>
      <div className="page-header"><div><Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate(backPath)} style={{ marginLeft: -8 }}>{provider ? '返回平台列表' : '返回设置'}</Button><Title level={3}>{provider === 'langfuse' ? 'Langfuse' : activeItem?.label || '设置'}</Title><Text type="secondary" className="page-header-copy">{tabKey === 'llm' ? '管理问答模型、降级链路与连接测试。' : tabKey === 'web-search' ? '仅在外部事实缺失或用户明确要求时联网补充。' : tabKey === 'observability' ? '统一记录 Agent 的问答、检索与模型调用链路。' : '独立配置页面。'}</Text></div>{tabKey === 'llm' && <Button type="primary" icon={<PlusOutlined />} onClick={handleCreate}>新增配置</Button>}</div>
      {activeItem?.children}

      <Modal title="配置 Langfuse" open={observabilityModalOpen} onCancel={() => { setObservabilityModalOpen(false); if (provider) navigate('/settings/observability') }} footer={null} destroyOnHidden width={560}>
        <Form form={observabilityForm} layout="vertical">
          <Form.Item name="langfuse_enabled" label="启用 Langfuse" valuePropName="checked"><Switch /></Form.Item>
          <Form.Item name="langfuse_host" label="Langfuse Host" extra="为保护密钥与上报数据，当前仅支持官方 Langfuse Cloud。"><Input disabled /></Form.Item>
          <Form.Item name="langfuse_public_key" label="Public Key" extra={observabilityConfig?.public_key_configured ? `当前：${observabilityConfig.langfuse_public_key}；留空表示不修改` : '在 Langfuse Project Settings 中获取'}><Input.Password autoComplete="new-password" placeholder="pk-lf-..." /></Form.Item>
          <Form.Item name="langfuse_secret_key" label="Secret Key" extra={observabilityConfig?.secret_key_configured ? `当前：${observabilityConfig.langfuse_secret_key}；留空表示不修改` : '在 Langfuse Project Settings 中获取'}><Input.Password autoComplete="new-password" placeholder="sk-lf-..." /></Form.Item>
          <Form.Item name="online_evaluation_enabled" label="为 Langfuse 在线 Judge 提供评分上下文" valuePropName="checked" extra="开启后，answer 节点会额外上传用户问题和实际检索证据；仅在你已在 Langfuse 配置 LLM-as-a-Judge 时开启。"><Switch /></Form.Item>
          <Space><Button onClick={testObservabilityConfig} loading={observabilityTesting} disabled={!observabilityConfig?.public_key_configured || !observabilityConfig?.secret_key_configured}>测试连接</Button><Button type="primary" onClick={saveObservabilityConfig} loading={observabilitySaving}>保存配置</Button></Space>
        </Form>
      </Modal>

      <Modal title={`配置 ${SEARCH_PROVIDERS.find(item => item.id === webSearchEditingProvider)?.name || '搜索服务'}`} open={webSearchModalOpen} onCancel={() => setWebSearchModalOpen(false)} footer={null} destroyOnHidden>
        <Form form={webSearchForm} layout="vertical">
          {(webSearchEditingProvider === 'duckduckgo' || webSearchEditingProvider === 'bing_rss')
            ? <Alert type="success" showIcon message="无需 API Key" description={webSearchEditingProvider === 'duckduckgo' ? 'DuckDuckGo 适合低频免费测试，可能受网络访问或限流影响。' : 'Bing RSS 为低频实验降级通道。'} style={{ marginBottom: 20 }} />
            : <Form.Item name={webSearchEditingProvider === 'exa' ? 'exa_api_key' : 'tavily_api_key'} label={`${webSearchEditingProvider === 'exa' ? 'Exa' : 'Tavily'} API Key`} extra={(webSearchEditingProvider === 'exa' ? webSearchConfig?.exa_api_key : webSearchConfig?.tavily_api_key) ? `当前：${webSearchEditingProvider === 'exa' ? webSearchConfig?.exa_api_key : webSearchConfig?.tavily_api_key}；留空表示不修改` : `${webSearchEditingProvider === 'exa' ? 'Exa' : 'Tavily'} 需要 API Key`}><Input.Password autoComplete="new-password" placeholder={`输入 ${webSearchEditingProvider === 'exa' ? 'Exa' : 'Tavily'} API Key`} /></Form.Item>}
          <Form.Item name="max_results" label="每次最多返回结果" rules={[{ required: true }]}><InputNumber min={1} max={10} style={{ width: '100%' }} /></Form.Item>
          <Space>
            <Button onClick={testWebSearchConfig} loading={webSearchTestingProvider === webSearchEditingProvider}>测试连接</Button>
            <Button type="primary" onClick={saveWebSearchConfig} loading={webSearchSaving}>保存配置</Button>
          </Space>
        </Form>
      </Modal>

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
            extra={editingId ? '留空表示不修改；测试会复用已保存的 API Key' : ''}
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

          <Form.Item name="role" label="调用角色" rules={[{ required: true, message: '请选择调用角色' }]}>
            <Select onChange={(role) => {
              if (!editingId) form.setFieldValue('is_active', role !== 'standalone')
            }} options={[
              { value: 'primary', label: '主模型（优先调用）' },
              { value: 'fallback', label: '降级模型（主模型失败后调用）' },
              { value: 'context', label: '重写 / 压缩模型（上下文处理）' },
              { value: 'standalone', label: '独立模型（创建后默认停用）' },
            ]} />
          </Form.Item>

          <Divider>上下文任务超时</Divider>
          <Alert type="info" showIcon message="重写或压缩超时会自动回退，不会中断最终问答。未单独配置上下文模型时，使用主模型的这两个值。" />
          <Row gutter={16} style={{ marginTop: 16 }}>
            <Col span={12}>
              <Form.Item name="context_rewrite_timeout_seconds" label="问题重写超时" initialValue={10} rules={[{ required: true }]}>
                <InputNumber min={3} max={30} addonAfter="秒" style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="context_compaction_timeout_seconds" label="会话压缩超时" initialValue={25} rules={[{ required: true }]}>
                <InputNumber min={5} max={60} addonAfter="秒" style={{ width: '100%' }} />
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
