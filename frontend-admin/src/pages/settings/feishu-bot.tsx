import { useEffect, useState } from 'react'
import { Alert, Button, Card, Empty, Form, Input, Modal, Popconfirm, Radio, Select, Space, Switch, Table, Tag, Typography, message } from 'antd'
import { ArrowLeftOutlined, BlockOutlined, MessageOutlined, PlusOutlined, ReloadOutlined, UserAddOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { api } from '@/services/api'

type Config = { enabled: boolean; app_id: string; app_secret: string; last_test_success: boolean | null; last_error: string | null; effective_app_id: string; use_cloud_config: boolean; response_detail: string; p2p_enabled: boolean; p2p_access_mode: string; p2p_agent_id: number | null; p2p_allow_openids: string }
type Agent = { id: number; name: string; is_active: boolean }
type Chat = { chat_id: string; name: string }
type Binding = { id: number; chat_id: string; chat_name: string; agent_id: number; agent_name: string; is_active: boolean }

export default function FeishuBotSettings() {
  const navigate = useNavigate()
  const [form] = Form.useForm()
  const [bindForm] = Form.useForm()
  const [config, setConfig] = useState<Config>()
  const [agents, setAgents] = useState<Agent[]>([])
  const [bindings, setBindings] = useState<Binding[]>([])
  const [chats, setChats] = useState<Chat[]>([])
  const [configOpen, setConfigOpen] = useState(false)
  const [bindOpen, setBindOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [loadingChats, setLoadingChats] = useState(false)
  const [listOpen, setListOpen] = useState(false)
  const [listItems, setListItems] = useState<string[]>([])
  const [newItem, setNewItem] = useState('')

  const load = async () => {
    try {
      const [c, a, b] = await Promise.all([api.get<Config>('/feishu-bot/config'), api.get<{ items: Agent[] }>('/agents'), api.get<Binding[]>('/feishu-bot/bindings')])
      setConfig(c); setAgents(a.items.filter(i => i.is_active)); setBindings(b)
    } catch { message.error('加载飞书机器人配置失败') }
  }
  useEffect(() => { void load() }, [])

  const loadChats = async () => {
    setLoadingChats(true)
    try { setChats(await api.get<Chat[]>('/feishu-bot/chats')) }
    catch (e: any) { message.error(e?.response?.data?.detail || '加载群列表失败，请确认机器人已加入群聊且应用具备 im:chat 权限') }
    finally { setLoadingChats(false) }
  }

  const save = async () => {
    const v = await form.validateFields(); setBusy(true)
    try { await api.put('/feishu-bot/config', { ...v, enabled: config?.enabled || false }); setConfigOpen(false); await load(); message.success('飞书机器人配置已保存') }
    catch (e: any) { message.error(e?.response?.data?.detail || '保存失败') }
    finally { setBusy(false) }
  }
  const test = async () => {
    setBusy(true)
    try { const r = await api.post<any>('/feishu-bot/config/test'); r.success ? message.success(r.message) : message.error(r.message); await load() }
    catch (e: any) { message.error(e?.response?.data?.detail || '测试失败') }
    finally { setBusy(false) }
  }
  const toggle = async () => {
    try { await api.put('/feishu-bot/config', { enabled: !config?.enabled, app_id: config?.app_id || '' }); await load(); message.success(config?.enabled ? '飞书机器人已停用' : '飞书机器人已启用') }
    catch (e: any) { message.error(e?.response?.data?.detail || '更新失败') }
  }
  const add = async () => {
    const v = await bindForm.validateFields()
    try { await api.post('/feishu-bot/bindings', v); setBindOpen(false); await load(); message.success('群已绑定 Agent') }
    catch (e: any) { message.error(e?.response?.data?.detail || '绑定失败') }
  }
  const openBind = (chat?: Chat) => {
    bindForm.resetFields()
    if (chat) { bindForm.setFieldsValue({ chat_id: chat.chat_id, chat_name: chat.name || '' }) }
    setBindOpen(true)
  }
  const del = async (id: number) => {
    try { await api.delete(`/feishu-bot/bindings/${id}`); await load(); message.success('已删除绑定') }
    catch (e: any) { message.error(e?.response?.data?.detail || '删除失败') }
  }
  const changeDetail = async (detail: string) => {
    try { await api.put('/feishu-bot/config/detail', { response_detail: detail }); await load(); message.success('回复详细程度已更新') }
    catch (e: any) { message.error(e?.response?.data?.detail || '更新失败') }
  }
  const changeP2p = async (patch: Partial<{ p2p_enabled: boolean; p2p_access_mode: string; p2p_agent_id: number | null; p2p_allow_openids: string }>) => {
    try {
      await api.put('/feishu-bot/config/p2p', {
        p2p_enabled: patch.p2p_enabled ?? config?.p2p_enabled ?? false,
        p2p_access_mode: patch.p2p_access_mode ?? config?.p2p_access_mode ?? 'all',
        p2p_agent_id: patch.p2p_agent_id !== undefined ? patch.p2p_agent_id : (config?.p2p_agent_id ?? null),
        p2p_allow_openids: patch.p2p_allow_openids !== undefined ? patch.p2p_allow_openids : (config?.p2p_allow_openids ?? ''),
      })
      await load(); message.success('私聊设置已更新')
    } catch (e: any) { message.error(e?.response?.data?.detail || '更新失败') }
  }
  const p2pMode = config?.p2p_access_mode || 'all'
  const openList = () => {
    setListItems((config?.p2p_allow_openids || '').split(',').map(s => s.trim()).filter(Boolean))
    setNewItem(''); setListOpen(true)
  }
  const addListItem = () => {
    const v = newItem.trim()
    if (!v) { message.warning('请输入 OpenID'); return }
    if (listItems.includes(v)) { message.warning('该 OpenID 已在名单中'); return }
    setListItems([...listItems, v]); setNewItem('')
  }
  const saveList = () => { changeP2p({ p2p_allow_openids: listItems.join(', ') }); setListOpen(false) }

  return <div>
    <div className="page-header"><div><Button type="text" icon={<ArrowLeftOutlined />} onClick={() => navigate('/settings/bots')} style={{ marginLeft: -8 }}>返回机器人</Button><Typography.Title level={3}>飞书机器人</Typography.Title><Typography.Text type="secondary">仅响应已绑定群内的 @机器人 消息。</Typography.Text></div></div>
    <Alert showIcon type="info" message="使用飞书应用机器人" description="通过官方 WebSocket 长连接接收消息，无需公网回调地址；需要在飞书开放平台为应用开启机器人能力并订阅 im.message.receive_v1 事件。" />
    <Card style={{ marginTop: 16 }}>
      <Space><Tag color={config?.enabled ? 'success' : 'default'}>{config?.enabled ? '已启用' : '未启用'}</Tag><Button onClick={test} loading={busy}>测试凭据</Button><Button onClick={() => { form.setFieldsValue({ app_id: config?.app_id || '', app_secret: '' }); setConfigOpen(true) }}>配置</Button><Button type={config?.enabled ? 'default' : 'primary'} onClick={toggle}>{config?.enabled ? '停用' : '启用'}</Button></Space>
      <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>{config?.use_cloud_config ? <>复用云文档飞书应用：<Typography.Text code>{config?.effective_app_id}</Typography.Text>（未单独配置时自动使用）</> : config?.last_error || (config?.enabled ? '启用后将自动建立飞书长连接。' : '请先配置 App ID 与 App Secret 并启用。')}</Typography.Paragraph>
    </Card>
    <Card title="回复与私聊设置" style={{ marginTop: 16 }}>
      <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>回复详细程度控制回答展开度；私聊默认关闭，开启后由「私聊默认 Agent」回答，白名单留空则开放给所有能私聊的用户。</Typography.Paragraph>
      <Space size={24} wrap align="center">
        <Radio.Group value={config?.response_detail || 'concise'} onChange={e => changeDetail(e.target.value)}>
          <Radio value="concise">简洁（默认）</Radio>
          <Radio value="detailed">详细</Radio>
        </Radio.Group>
      </Space>
      <div style={{ marginTop: 14, paddingTop: 14, borderTop: '1px dashed #e8ecf4' }}>
        <Space size={24} wrap align="center">
          <span>私聊：<Switch checked={config?.p2p_enabled || false} onChange={v => changeP2p({ p2p_enabled: v })} /></span>
          <span>私聊默认 Agent：</span>
          <Select
            allowClear placeholder="选择私聊回答的 Agent" style={{ width: 200 }}
            value={config?.p2p_agent_id ?? undefined}
            onChange={v => changeP2p({ p2p_agent_id: v as number | null })}
            options={agents.map(a => ({ value: a.id, label: a.name }))}
          />
        </Space>
        <div style={{ marginTop: 10 }}>
          <Space wrap align="center">
            <span>权限模式：</span>
            <Select
              style={{ width: 180 }}
              value={p2pMode}
              onChange={v => changeP2p({ p2p_access_mode: v })}
              options={[
                { value: 'all', label: '开放所有人' },
                { value: 'allowlist', label: '仅白名单可访问' },
                { value: 'blocklist', label: '黑名单不可访问' },
              ]}
            />
            {p2pMode === 'allowlist' && <Button icon={<UserAddOutlined />} onClick={openList}>白名单设置</Button>}
            {p2pMode === 'blocklist' && <Button icon={<BlockOutlined />} onClick={openList}>黑名单设置</Button>}
            {p2pMode === 'all' && <Typography.Text type="secondary">开放所有人，无需名单</Typography.Text>}
          </Space>
          {(p2pMode === 'allowlist' || p2pMode === 'blocklist') && (
            <Typography.Text type="secondary" style={{ display: 'block', marginTop: 6 }}>
              {p2pMode === 'allowlist' ? `白名单 ${listItems.length || ((config?.p2p_allow_openids || '').split(',').filter(x => x.trim()).length)} 人` : `黑名单 ${listItems.length || ((config?.p2p_allow_openids || '').split(',').filter(x => x.trim()).length)} 人`}
            </Typography.Text>
          )}
        </div>
      </div>
    </Card>
    <Card title="机器人所在群" style={{ marginTop: 16 }} extra={<Button icon={<ReloadOutlined />} loading={loadingChats} disabled={!config?.enabled} onClick={loadChats}>刷新群列表</Button>}>
      <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>机器人已加入的群（来自飞书 im/v1/chats）；点击群标签可快捷绑定 Agent。若列表为空，请确认机器人为应用机器人并已入群。</Typography.Paragraph>
      {chats.length === 0
        ? <Typography.Text type="secondary">（空）点击「刷新群列表」加载</Typography.Text>
        : <Space wrap>{chats.map(chat => {
            const bound = bindings.find(b => b.chat_id === chat.chat_id)
            return <Tag key={chat.chat_id} color={bound ? 'success' : 'blue'} style={{ cursor: 'pointer' }} onClick={() => bound ? message.info(`该群已绑定 Agent「${bound.agent_name}」`) : openBind(chat)}>{chat.name || chat.chat_id}{bound ? '（已绑定）' : ' ＋绑定'}</Tag>
          })}</Space>}
    </Card>
    <Card title="群 → Agent 绑定" style={{ marginTop: 16 }} extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => openBind()}>绑定群</Button>}>
      <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>已绑定的群；该群内 @机器人 的消息将交给绑定的 Agent 回答。</Typography.Paragraph>
      <Table rowKey="id" dataSource={bindings} pagination={false} columns={[
        { title: '群', render: (_: unknown, row: Binding) => <>{row.chat_name || row.chat_id}<Typography.Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>{row.chat_name ? row.chat_id : ''}</Typography.Text></> },
        { title: 'Agent', dataIndex: 'agent_name' },
        { title: '状态', render: (_: unknown, row: Binding) => <Tag color={row.is_active ? 'success' : 'default'}>{row.is_active ? '启用' : '停用'}</Tag> },
        { title: '操作', render: (_: unknown, row: Binding) => <Popconfirm title="删除该群绑定？" onConfirm={() => del(row.id)}><Button type="text" danger size="small">删除</Button></Popconfirm> },
      ]} />
    </Card>
    <Modal title="配置飞书机器人" open={configOpen} onCancel={() => setConfigOpen(false)} footer={null} destroyOnHidden>
      <Form form={form} layout="vertical">
        <Form.Item name="app_id" label="App ID" rules={[{ required: true, message: '请输入 App ID' }]}><Input autoComplete="off" placeholder="cli_xxx" /></Form.Item>
        <Form.Item name="app_secret" label="App Secret" extra={config?.use_cloud_config ? '已复用云文档应用凭据，留空表示继续复用；如需独立配置请填写' : '已保存密钥不会回显；留空表示不修改'}><Input.Password autoComplete="new-password" /></Form.Item>
        <Button type="primary" onClick={save} loading={busy}>保存配置</Button>
      </Form>
    </Modal>
    <Modal title="绑定飞书群" open={bindOpen} onCancel={() => setBindOpen(false)} footer={null} destroyOnHidden>
      <Form form={bindForm} layout="vertical">
        <Form.Item name="chat_id" label="飞书群" rules={[{ required: true, message: '请选择群' }]}>
          <Select placeholder={chats.length ? '选择群' : '先在上方「机器人所在群」点击「刷新群列表」'} options={chats.map(c => ({ value: c.chat_id, label: c.name ? `${c.name}（${c.chat_id}）` : c.chat_id }))} onChange={(v: string) => { const chat = chats.find(c => c.chat_id === v); bindForm.setFieldValue('chat_name', chat?.name || '') }} />
        </Form.Item>
        <Form.Item name="chat_name" label="群名称" hidden><Input /></Form.Item>
        <Form.Item name="agent_id" label="Agent" rules={[{ required: true, message: '请选择 Agent' }]}>
          <Select placeholder="选择回答该群消息的 Agent" options={agents.map(a => ({ value: a.id, label: a.name }))} />
        </Form.Item>
        <Button type="primary" icon={<MessageOutlined />} onClick={add}>绑定</Button>
      </Form>
    </Modal>
    <Modal title={p2pMode === 'blocklist' ? '黑名单设置' : '白名单设置'} open={listOpen} onCancel={() => setListOpen(false)} onOk={saveList} okText="保存" cancelText="取消" destroyOnHidden>
      <Typography.Paragraph type="secondary" style={{ marginTop: 0 }}>{p2pMode === 'blocklist' ? '名单内的用户将无法私聊机器人。' : '仅名单内的用户可以私聊机器人（名单为空则无人可访问）。'}</Typography.Paragraph>
      <Space.Compact style={{ width: '100%', marginBottom: 12 }}>
        <Input placeholder="输入用户 OpenID，如 ou_xxx" value={newItem} onChange={e => setNewItem(e.target.value)} onPressEnter={addListItem} />
        <Button type="primary" onClick={addListItem}>添加</Button>
      </Space.Compact>
      {listItems.length === 0
        ? <Empty description="名单为空" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        : listItems.map(v => (
          <div key={v} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 10px', borderBottom: '1px solid #f0f0f0' }}>
            <Typography.Text code>{v}</Typography.Text>
            <Button type="text" danger size="small" onClick={() => setListItems(listItems.filter(x => x !== v))}>删除</Button>
          </div>
        ))}
    </Modal>
  </div>
}
