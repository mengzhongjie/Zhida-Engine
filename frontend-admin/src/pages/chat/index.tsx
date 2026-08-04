import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Button, Empty, Select, Spin, Tag, Typography, message } from 'antd'
import { SendOutlined } from '@ant-design/icons'
import { api } from '@/services/api'

const { Text } = Typography

type Agent = { id: number; name: string; description?: string; avatar?: string; is_active: boolean }
type Source = { document_name: string; chunk_text: string; score: number; source_type: string }
type Answer = { answer: string; sources: Source[]; response_time_ms: number; model_used: string; from_cache: boolean }
type ChatMessage = { id: string; role: 'user' | 'assistant'; content: string; sources?: Source[]; meta?: Pick<Answer, 'response_time_ms' | 'model_used' | 'from_cache'>; pending?: boolean }

const createId = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`

export default function Chat() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [agentId, setAgentId] = useState<number>()
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loadingAgents, setLoadingAgents] = useState(true)
  const [asking, setAsking] = useState(false)
  const [mobile, setMobile] = useState(() => window.innerWidth <= 720)
  const bottomRef = useRef<HTMLDivElement>(null)
  const sessionIdRef = useRef(`admin-${createId()}`)

  const selectedAgent = useMemo(() => agents.find(agent => agent.id === agentId), [agents, agentId])

  useEffect(() => {
    api.get<{ items: Agent[] }>('/agents')
      .then(result => {
        const active = result.items.filter(agent => agent.is_active)
        setAgents(active)
        setAgentId(active[0]?.id)
      })
      .catch(() => message.error('加载 Agent 列表失败'))
      .finally(() => setLoadingAgents(false))
  }, [])

  useEffect(() => {
    const update = () => setMobile(window.innerWidth <= 720)
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, asking])

  const resetConversation = () => {
    setMessages([])
    setInput('')
    sessionIdRef.current = `admin-${createId()}`
  }

  const selectAgent = (nextAgentId: number) => {
    if (asking || nextAgentId === agentId) return
    setAgentId(nextAgentId)
    resetConversation()
  }

  const send = async () => {
    const question = input.trim()
    if (!question || !agentId || asking) return
    const userMessage: ChatMessage = { id: createId(), role: 'user', content: question }
    const pendingId = createId()
    setMessages(previous => [...previous, userMessage, { id: pendingId, role: 'assistant', content: '', pending: true }])
    setInput('')
    setAsking(true)
    try {
      const token = localStorage.getItem('zhida_admin_token')
      const response = await fetch('/api/v1/qa/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Chat-Id': sessionIdRef.current,
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          agent_id: agentId,
          question,
          chat_id: sessionIdRef.current,
          chat_type: 'private',
          user_id: 'admin-console',
          stream: true,
        }),
      })
      if (!response.ok || !response.body) {
        const data = await response.json().catch(() => ({}))
        throw new Error(data.detail || '无法建立流式回答连接')
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let completed = false
      const applyEvent = (event: string, rawData: string) => {
        const data = JSON.parse(rawData)
        if (event === 'delta') {
          setMessages(previous => previous.map(item => item.id === pendingId ? {
            ...item, pending: false, content: item.content + (data.content || ''),
          } : item))
        } else if (event === 'done') {
          completed = true
          setMessages(previous => previous.map(item => item.id === pendingId ? {
            ...item,
            pending: false,
            sources: data.sources || [],
            meta: { response_time_ms: data.response_time_ms || 0, model_used: data.model_used || '', from_cache: false },
          } : item))
        } else if (event === 'error') {
          throw new Error(data.detail || '流式回答失败')
        }
      }
      while (true) {
        const { done, value } = await reader.read()
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
        const events = buffer.split('\n\n')
        buffer = events.pop() || ''
        for (const item of events) {
          const event = item.match(/^event:\s*(.+)$/m)?.[1] || 'message'
          const rawData = item.match(/^data:\s*(.+)$/m)?.[1]
          if (rawData) applyEvent(event, rawData)
        }
        if (done) break
      }
      if (!completed) throw new Error('流式回答意外中断')
    } catch (error: any) {
      const detail = error?.response?.data?.detail
      setMessages(previous => previous.map(item => item.id === pendingId ? {
        id: pendingId, role: 'assistant', content: `本轮问答未完成：${typeof detail === 'string' ? detail : '请检查 Agent 与模型配置后重试。'}`,
      } : item))
    } finally {
      setAsking(false)
    }
  }

  return <div className="chat-page">
    {!loadingAgents && !agents.length && <Alert showIcon type="warning" message="暂无已启用的 Agent" description="请先在 Agent 管理中启用一个 Agent，再回到此处发起对话。" />}
    <div className="chat-mobile-agent-picker"><Select value={agentId} loading={loadingAgents} disabled={asking || !agents.length} onChange={selectAgent} options={agents.map(agent => ({ value: agent.id, label: agent.name }))} /></div>
    <section className="chat-workspace">
      <aside className="chat-agent-list" aria-label="Agent 列表">
        <div className="chat-agent-list-title">我的 Agent <span>{agents.length}</span></div>
        {loadingAgents ? <div className="chat-agent-list-loading"><Spin size="small" /></div> : agents.map(agent => <button type="button" key={agent.id} className={`chat-agent-item ${agent.id === agentId ? 'is-selected' : ''}`} onClick={() => selectAgent(agent.id)} disabled={asking}>
          <span className="chat-agent-avatar">{agent.avatar || agent.name.slice(0, 1)}</span>
          <span><strong>{agent.name}</strong><small>{agent.description || '已启用'}</small></span>
        </button>)}
      </aside>
      <div className="chat-shell">
        <div className="chat-context">
        <span className="chat-agent-avatar">{selectedAgent?.avatar || 'AI'}</span>
        <div><Text strong>{selectedAgent?.name || '请选择 Agent'}</Text><Text type="secondary">{selectedAgent?.description || '回答会结合该 Agent 已挂载的知识库。'}</Text></div>
      </div>
        <div className="chat-messages">
        {!messages.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="从一个问题开始。回答会结合当前 Agent 已挂载的知识库。" className="chat-empty" />}
        {messages.map(item => <article className={`chat-message chat-message-${item.role}`} key={item.id}>
          <div className="chat-message-label">{item.role === 'user' ? '你' : (selectedAgent?.name || 'AI')}</div>
          <div className={`chat-bubble ${item.pending ? 'is-pending' : ''}`}>
            {item.pending ? <Spin size="small" tip="正在检索并生成回答…" /> : <div className="chat-content">{item.content}</div>}
          </div>
          {item.sources && item.sources.length > 0 && <div className="chat-reference"><span>引用资料</span>{[...new Set(item.sources.map(source => source.document_name))].map(name => <Tag key={name}>{name}</Tag>)}</div>}
          {item.meta && <div className="chat-meta"><span>{item.meta.model_used || '已配置模型'}</span><span>{Math.round(item.meta.response_time_ms)} ms</span>{item.meta.from_cache && <span>缓存命中</span>}</div>}
        </article>)}
        <div ref={bottomRef} />
        </div>
        <div className="chat-composer">
        <textarea value={input} onChange={event => setInput(event.target.value)} onKeyDown={event => {
          if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) { event.preventDefault(); void send() }
        }} placeholder={agentId ? (mobile ? '输入问题…' : '输入问题；Enter 换行，Ctrl/Cmd + Enter 发送') : '请先选择已启用 Agent'} disabled={!agentId || asking} rows={3} />
        <Button type="primary" icon={<SendOutlined />} onClick={() => void send()} loading={asking} disabled={!input.trim() || !agentId}>发送</Button>
        </div>
      </div>
    </section>
  </div>
}
