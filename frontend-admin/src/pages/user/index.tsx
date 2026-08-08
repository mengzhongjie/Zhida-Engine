import { useEffect, useMemo, useRef, useState } from 'react'
import { Button, Drawer, Empty, Segmented, Typography, message } from 'antd'
import { HistoryOutlined, LogoutOutlined, MenuOutlined, SendOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const { Text, Title } = Typography

type Agent = { id: number; name: string; description?: string; avatar?: string }
type Conversation = { id: string; agent_id: number; title: string; updated_at: string }
type Source = { metadata?: { filename?: string }; document_name?: string }
type ChatMessage = { id: string; role: 'user' | 'assistant'; content: string; sources?: Source[]; pending?: boolean; streaming?: boolean; statusText?: string }

const createId = () => globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`

export default function UserPage() {
  const navigate = useNavigate()
  const [agents, setAgents] = useState<Agent[]>([])
  const [agentId, setAgentId] = useState<number>()
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [conversationId, setConversationId] = useState<string>()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [responseDetail, setResponseDetail] = useState<'concise' | 'detailed'>('concise')
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [remainingToday, setRemainingToday] = useState<number | null>(null)
  const [developmentMode, setDevelopmentMode] = useState(false)
  const [compactViewport, setCompactViewport] = useState(() => window.matchMedia('(max-width: 820px)').matches)
  const bottomRef = useRef<HTMLDivElement>(null)
  const selectedAgent = useMemo(() => agents.find(item => item.id === agentId), [agents, agentId])

  const load = async () => {
    try {
      const [agentResponse, conversationResponse, profileResponse] = await Promise.all([
        fetch('/api/v1/user/agents', { credentials: 'include' }),
        fetch('/api/v1/user/conversations', { credentials: 'include' }),
        fetch('/api/v1/user/me', { credentials: 'include' }),
      ])
      if (!agentResponse.ok || !conversationResponse.ok || !profileResponse.ok) throw new Error('加载失败')
      const agentData = await agentResponse.json()
      const conversationData = await conversationResponse.json()
      const profileData = await profileResponse.json()
      const availableAgents = agentData.items || []
      setAgents(availableAgents)
      // 登录后先由用户明确选择助手，避免误把问题发给默认 Agent。
      setAgentId(previous => previous && availableAgents.some((item: Agent) => item.id === previous) ? previous : undefined)
      setConversations(conversationData.items || [])
      setRemainingToday(typeof profileData.remaining_today === 'number' ? profileData.remaining_today : null)
      setDevelopmentMode(profileData.development_mode === true)
    } catch {
      message.error('加载用户信息失败，请重新登录后重试')
    }
  }

  useEffect(() => { void load() }, [])
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])
  useEffect(() => {
    const query = window.matchMedia('(max-width: 820px)')
    const update = () => setCompactViewport(query.matches)
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])

  const selectAgent = (nextAgentId: number) => {
    if (sending) return
    setAgentId(nextAgentId)
    setConversationId(undefined)
    setMessages([])
    setSidebarOpen(false)
  }

  const openConversation = async (item: Conversation) => {
    try {
      const response = await fetch(`/api/v1/user/conversations/${item.id}`, { credentials: 'include' })
      if (!response.ok) throw new Error('加载历史失败')
      const data = await response.json()
      setAgentId(item.agent_id)
      setConversationId(item.id)
      setMessages((data.items || []).flatMap((record: { id: number; question: string; answer: string; sources?: Source[] }) => [
        { id: `question-${record.id}`, role: 'user' as const, content: record.question },
        { id: `answer-${record.id}`, role: 'assistant' as const, content: record.answer, sources: record.sources || [] },
      ]))
      setSidebarOpen(false)
    } catch {
      message.error('历史对话加载失败')
    }
  }

  const send = async () => {
    const question = input.trim()
    if (!question || !agentId || sending || developmentMode) return

    const pendingId = createId()
    setMessages(previous => [
      ...previous,
      { id: createId(), role: 'user', content: question },
      { id: pendingId, role: 'assistant', content: '', pending: true, streaming: true },
    ])
    setInput('')
    setSending(true)

    try {
      const response = await fetch('/api/v1/user/chat/stream', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: agentId, question, conversation_id: conversationId, response_detail: responseDetail }),
      })
      if (!response.ok || !response.body) {
        const data = await response.json().catch(() => ({}))
        throw new Error(data.detail || '无法开始回答')
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let completed = false

      const applyEvent = (kind: string, raw: string) => {
        const data = JSON.parse(raw)
        if (kind === 'status') {
          setMessages(previous => previous.map(item => item.id === pendingId
            ? { ...item, statusText: data.detail || '正在处理上下文…' }
            : item))
        } else if (kind === 'delta') {
          setMessages(previous => previous.map(item => item.id === pendingId
            ? { ...item, pending: false, streaming: true, statusText: undefined, content: item.content + (data.content || '') }
            : item))
        } else if (kind === 'done') {
          completed = true
          setConversationId(data.conversation_id)
          setRemainingToday(typeof data.remaining_today === 'number' ? data.remaining_today : remainingToday)
          setMessages(previous => previous.map(item => item.id === pendingId
            ? { ...item, pending: false, streaming: false, sources: data.sources || [] }
            : item))
          void load()
        } else if (kind === 'error') {
          throw new Error(data.detail || '回答失败')
        }
      }

      while (true) {
        const { done, value } = await reader.read()
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
        const events = buffer.split('\n\n')
        buffer = events.pop() || ''
        for (const event of events) {
          const kind = event.match(/^event:\s*(.+)$/m)?.[1] || 'message'
          const raw = event.match(/^data:\s*(.+)$/m)?.[1]
          if (raw) applyEvent(kind, raw)
        }
        if (done) break
      }
      if (!completed) throw new Error('回答连接意外中断')
    } catch (error: any) {
      setMessages(previous => previous.map(item => item.id === pendingId
        ? { ...item, pending: false, content: error?.message || '回答失败，请稍后重试。' }
        : item))
    } finally {
      setSending(false)
    }
  }

  const logout = async () => {
    await fetch('/api/v1/auth/logout', { method: 'POST', credentials: 'include' })
    navigate('/login', { replace: true })
  }

  const renderSidebar = () => <>
    <div className="user-sidebar-brand"><Title level={4}>智答助手</Title><Button type="text" aria-label="退出登录" icon={<LogoutOutlined />} onClick={() => void logout()} /></div>
    <div className="user-sidebar-section-title">我的助手</div>
    <section className="user-sidebar-agents" aria-label="已授权 Agent">
      {agents.map(item => <button type="button" key={item.id} className={item.id === agentId ? 'active' : ''} onClick={() => selectAgent(item.id)}>
        <b>{item.avatar || item.name.slice(0, 1)}</b><span>{item.name}<small>{item.description || '专属知识助手'}</small></span>
      </button>)}
    </section>
    <div className="user-sidebar-section-title history"><HistoryOutlined /> 历史对话</div>
    <section className="user-sidebar-history">
      {conversations.length
        ? conversations.map(item => <button type="button" key={item.id} className={item.id === conversationId ? 'active' : ''} onClick={() => void openConversation(item)}><span>{item.title}</span><small>{agents.find(agent => agent.id === item.agent_id)?.name || '助手'}</small></button>)
        : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无历史对话" />}
    </section>
  </>

  return <main className="user-page">
    <header className="user-mobile-header"><Button type="text" icon={<MenuOutlined />} onClick={() => setSidebarOpen(true)} /><div><b>{selectedAgent?.name || '选择助手'}</b>{selectedAgent?.description && <small>{selectedAgent.description}</small>}</div><Button type="text" aria-label="退出登录" icon={<LogoutOutlined />} onClick={() => void logout()} /></header>
    <div className="user-workspace"><aside className="user-sidebar">{renderSidebar()}</aside>
    <Drawer className="user-sidebar-drawer" title="智答助手" placement="left" open={sidebarOpen} onClose={() => setSidebarOpen(false)} width={300}>{renderSidebar()}</Drawer>
    <section className="user-chat">
      <div className="user-chat-title">{selectedAgent?.name || '选择助手'}{selectedAgent?.description && <Text type="secondary">{selectedAgent.description}</Text>}</div>
      <div className="user-messages">
        {developmentMode && <div className="user-development-notice" role="status"><strong>系统正在开发维护</strong><span>问答功能暂时不可用，请稍后再试。</span></div>}
        {!messages.length && (agentId ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="有什么想了解的？" /> : agents.length ? <div className="user-agent-chooser"><header><b>选择助手</b><span>开始一段新的对话</span></header><div>{agents.map(item => <Button key={item.id} onClick={() => selectAgent(item.id)}><i>{item.avatar || item.name.slice(0, 1)}</i><section><strong>{item.name}</strong>{item.description && <small>{item.description}</small>}</section><em>开始对话</em></Button>)}</div></div> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无可用助手" />)}
        {messages.map(item => <article key={item.id} className={`user-message ${item.role}`}>
          <div>{item.role === 'user' ? '我' : 'AI'}</div>
          <section className={item.streaming ? 'is-streaming' : ''}>{item.pending ? <div className="stream-thinking" role="status"><span className="stream-thinking-dots"><i /><i /><i /></span><span>{item.statusText || '正在生成回答'}</span></div> : item.role === 'assistant' ? <div className="markdown-content"><ReactMarkdown remarkPlugins={[remarkGfm]}>{item.content}</ReactMarkdown>{item.streaming && <span className="stream-caret" aria-hidden="true" />}</div> : <span>{item.content}</span>}</section>
          {item.role === 'assistant' && !item.pending && <div className="ai-answer-disclaimer">回答由 AI 生成，知识库可能包含老旧信息，仅供参考。</div>}
        </article>)}
        <div ref={bottomRef} />
      </div>
      <div className="user-composer">
        <div className="user-composer-input">{remainingToday !== null && <small>今日剩余 {remainingToday} 次</small>}<textarea value={input} onChange={event => setInput(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) { event.preventDefault(); void send() } }} placeholder={developmentMode ? '系统维护中…' : compactViewport ? '输入问题…' : '输入问题；Enter 换行，Ctrl/Cmd + Enter 发送'} disabled={!agentId || sending || developmentMode} rows={2} /></div>
        <div className="user-composer-actions"><Segmented className="response-detail-picker" value={responseDetail} onChange={value => setResponseDetail(value as 'concise' | 'detailed')} options={[{ value: 'concise', label: '简洁' }, { value: 'detailed', label: '详细' }]} disabled={sending || developmentMode} /><div className="user-composer-actions-right"><Button type="primary" icon={<SendOutlined />} disabled={!input.trim() || sending || !agentId || developmentMode} loading={sending} onClick={() => void send()}>发送</Button></div></div>
      </div>
    </section></div>
  </main>
}
