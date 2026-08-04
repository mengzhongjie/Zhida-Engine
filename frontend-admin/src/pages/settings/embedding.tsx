import { useEffect, useState } from 'react'
import { Alert, Button, Card, Form, Input, InputNumber, Modal, Popconfirm, Select, Space, Tag, Typography, message } from 'antd'
import { ArrowLeftOutlined, DatabaseOutlined, DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api } from '@/services/api'

const { Title, Text } = Typography
type ModelOption = { model: string; dimension: number }
type Provider = { provider_id: string; name: string; base_url: string; default_model: string; default_dimension: number; available_models: ModelOption[] }
type Profile = { id: number; name: string; provider_id: string; provider_name: string; mode: 'cloud'; cloud_base_url: string; cloud_api_key: string; cloud_model: string; cloud_dimension: number; model: string; dimension?: number; is_primary: boolean; is_active: boolean; last_test_success: boolean|null; last_error: string|null }
type Current = { is_ready: boolean; current_model: string; current_dimension: number }
type KnowledgeBase = { id: number; name: string; document_count: number }
type KnowledgeBaseList = { items: KnowledgeBase[] }

export default function EmbeddingSettings() {
  const navigate = useNavigate(); const [form] = Form.useForm()
  const [profiles, setProfiles] = useState<Profile[]>([]); const [providers, setProviders] = useState<Provider[]>([])
  const [current, setCurrent] = useState<Current|null>(null); const [editing, setEditing] = useState<Profile|null>(null)
  const [open, setOpen] = useState(false); const [saving, setSaving] = useState(false); const [testingId, setTestingId] = useState<number|null>(null)
  const [rebuilding, setRebuilding] = useState(false)
  const [models, setModels] = useState<ModelOption[]>([])
  const load = async () => { try { const [items, active, providerGroups] = await Promise.all([api.get<Profile[]>('/embedding/profiles'), api.get<Current>('/embedding/config'), api.get<{cloud:Provider[];custom:Provider[]}>('/embedding/providers')]); setProfiles(items); setCurrent(active); setProviders([...providerGroups.cloud, ...providerGroups.custom]) } catch { message.error('加载向量模型配置失败') } }
  useEffect(() => { load() }, [])
  const edit = (item?: Profile) => { setEditing(item || null); const provider = item && providers.find(p => p.provider_id === item.provider_id); setModels(provider?.available_models || []); form.setFieldsValue(item ? { ...item, cloud_api_key: '' } : { name: '向量模型', mode: 'cloud', cloud_dimension: 1024 }); setOpen(true) }
  const providerChanged = async (providerId: string) => { const result = await api.post<any>('/embedding/providers/autofill', { provider_id: providerId }); setModels(result.available_models || []); form.setFieldsValue({ provider_id: result.provider_id, provider_name: result.provider_name, cloud_base_url: result.base_url, cloud_model: result.default_model, cloud_dimension: result.default_dimension }) }
  const modelChanged = (model: string) => { const match = models.find(m => m.model === model); if (match) form.setFieldValue('cloud_dimension', match.dimension) }
  const save = async () => { const values = await form.validateFields(); values.is_active = editing?.is_active ?? true; setSaving(true); try { if (editing) await api.put(`/embedding/profiles/${editing.id}`, values); else await api.post('/embedding/profiles', values); setOpen(false); await load(); message.success('向量配置已保存') } catch (e:any) { message.error(e?.response?.data?.detail || '保存失败') } finally { setSaving(false) } }
  const test = async (item:Profile) => { setTestingId(item.id); try { const result = await api.post<any>(`/embedding/profiles/${item.id}/test`); result.success ? message.success(`${result.message}，${result.dimension} 维`) : message.error(result.message); await load() } catch(e:any) { message.error(e?.response?.data?.detail || '测试失败') } finally { setTestingId(null) } }
  const activate = async (item:Profile, rebuild=false) => { try { const result = await api.post<any>(`/embedding/profiles/${item.id}/activate${rebuild?'?rebuild=true':''}`); await load(); message.success(result.rebuild_started ? `已切换，正在重建 ${result.rebuild_started} 个知识库` : '已切换主向量模型') } catch(e:any) { const detail=e?.response?.data?.detail; if (!rebuild && detail?.requires_rebuild) Modal.confirm({ title:'切换需要重建索引', content:`将切换主向量模型，并异步重建 ${detail.knowledge_base_count} 个知识库。重建期间暂不提供这些知识库的问答。`, okText:'确认切换并重建', onOk:()=>activate(item,true) }); else message.error(detail?.message || detail || '切换失败') } }
  const toggle = async (item:Profile) => { try { await api.put(`/embedding/profiles/${item.id}`, { ...item, cloud_api_key:'', is_active:!item.is_active }); await load() } catch(e:any) { message.error(e?.response?.data?.detail || '更新失败') } }
  const remove = async(id:number) => { try { await api.delete(`/embedding/profiles/${id}`); await load(); message.success('已删除') } catch(e:any){ message.error(e?.response?.data?.detail || '删除失败') } }
  const rebuildAll = async () => {
    setRebuilding(true)
    try {
      const { items } = await api.get<KnowledgeBaseList>('/knowledge/bases')
      const targets = items.filter(item => item.document_count > 0)
      if (!targets.length) { message.info('没有包含文档的知识库需要重建'); return }
      const results = await Promise.allSettled(targets.map(item => api.post(`/knowledge/bases/${item.id}/rebuild-index`)))
      const started = results.filter(result => result.status === 'fulfilled').length
      const failed = results.length - started
      message.success(`已启动 ${started} 个知识库的索引重建${failed ? `，${failed} 个未启动` : ''}`)
    } catch (e: any) { message.error(e?.response?.data?.detail || '启动索引重建失败') } finally { setRebuilding(false) }
  }
  const confirmRebuild = () => Modal.confirm({ title: '重建全部知识库索引？', content: '会为每个知识库创建本地备份，然后按当前主向量模型重新向量化。重建期间对应知识库暂不可问答。', okText: '开始重建', okButtonProps: { danger: true }, onOk: rebuildAll })
  return <div><div className="page-header"><div><Button type="text" icon={<ArrowLeftOutlined/>} onClick={()=>navigate('/settings')} style={{marginLeft:-8}}>返回设置</Button><Title level={3}>向量化模型</Title><Text type="secondary">可以保存多套配置，运行时使用当前主模型。</Text></div><Space><Button icon={<ReloadOutlined/>} loading={rebuilding} onClick={confirmRebuild}>重建索引</Button><Button type="primary" icon={<PlusOutlined/>} onClick={()=>edit()}>新增配置</Button></Space></div>
    <div className="web-search-settings"><Alert type="warning" showIcon message="切换模型必须重建索引" description={`当前：${current?.current_model || '检测中'} · ${current?.current_dimension || 0} 维 · ${current?.is_ready?'可用':'未就绪'}`} />
      <div className="web-search-provider-list">{profiles.map(item=><Card key={item.id} size="small" className={`web-search-provider-card ${item.is_primary&&item.is_active?'is-active':''}`}><div className="web-search-provider-main"><div><Space><DatabaseOutlined style={{color:'#1677ff'}}/><Text strong>{item.name}</Text>{item.is_primary&&<Tag color="blue">主模型</Tag>}</Space><Text type="secondary">{item.provider_name} · {item.model}{item.dimension?` · ${item.dimension} 维`:''}</Text></div><div className="web-search-provider-status"><Tag className={item.is_active?'search-chain-active':undefined} color={item.is_active?'success':'default'}>{item.is_active?'已启用':'已停用'}</Tag><Text type={item.last_test_success===false?'danger':'secondary'}>{item.last_test_success===true?'可用':item.last_test_success===false?'不可用':'待检测'}</Text></div></div><Text className="web-search-health-copy" type="secondary">{item.last_error || (item.is_primary?'正在用于知识库索引':'备用配置，不会自动降级')}</Text><Space wrap className="web-search-provider-actions"><Button onClick={()=>test(item)} loading={testingId===item.id}>测试连接</Button><Button icon={<EditOutlined/>} onClick={()=>edit(item)}>配置</Button>{!item.is_primary&&<Button type="primary" disabled={!item.is_active} onClick={()=>activate(item)}>设为主模型</Button>}<Button disabled={item.is_primary} onClick={()=>toggle(item)}>{item.is_active?'停用':'启用'}</Button><Popconfirm title="删除这条向量配置？" onConfirm={()=>remove(item.id)}><Button danger icon={<DeleteOutlined/>} disabled={item.is_primary}>删除</Button></Popconfirm></Space></Card>)}</div>
    </div>
    <Modal title={editing?'编辑向量配置':'新增向量配置'} open={open} onCancel={()=>setOpen(false)} footer={null} destroyOnHidden><Form form={form} layout="vertical"><Form.Item name="mode" initialValue="cloud" hidden><Input/></Form.Item><Form.Item name="name" label="配置名称" rules={[{required:true}]}><Input/></Form.Item><Form.Item name="provider_id" label="厂商" rules={[{required:true}]}><Select onChange={providerChanged} options={providers.map(p=>({value:p.provider_id,label:p.name}))}/></Form.Item><Form.Item name="provider_name" hidden><Input/></Form.Item><Form.Item name="cloud_base_url" label="API 地址" rules={[{required:true}]}><Input/></Form.Item><Form.Item name="cloud_api_key" label="API Key" extra={editing?.cloud_api_key?`当前：${editing.cloud_api_key}；留空表示不修改`:''}><Input.Password autoComplete="new-password"/></Form.Item><Form.Item name="cloud_model" label="模型" rules={[{required:true}]}>{models.length?<Select onChange={modelChanged} options={models.map(m=>({value:m.model,label:`${m.model} (${m.dimension}维)`}))}/>:<Input/>}</Form.Item><Form.Item name="cloud_dimension" label="向量维度" rules={[{required:true}]}><InputNumber min={1} style={{width:'100%'}}/></Form.Item><Button type="primary" onClick={save} loading={saving}>保存配置</Button></Form></Modal>
  </div>
}
