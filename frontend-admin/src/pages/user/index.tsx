import { useEffect, useMemo, useRef, useState } from 'react'
import { Button, Empty, Spin, Tag, Typography, message } from 'antd'
import { HistoryOutlined, LogoutOutlined, PlusOutlined, SendOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'

const { Text, Title } = Typography

type Agent = { id: number; name: string; description?: string; avatar?: string }
type Conversation = { id: string; agent_id: number; title: string; updated_at: string }
type Source = { metadata?: { filename?: string }; document_name?: string }
type ChatMessage = { id: string; role: 'user' | 'assistant'; content: string; sources?: Source[]; pending?: boolean }

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
  const [showHistory, setShowHistory] = useState(false)
  const [remainingToday, setRemainingToday] = useState<number | null>(null)
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
      setAgentId(previous => previous && availableAgents.some((item: Agent) => item.id === previous) ? previous : availableAgents[0]?.id)
      setConversations(conversationData.items || [])
      setRemainingToday(typeof profileData.remaining_today === 'number' ? profileData.remaining_today : null)
    } catch {
      message.error('加载用户信息失败，请重新登录后重试')
    }
  }

  useEffect(() => { void load() }, [])
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages])

  const selectAgent = (nextAgentId: number) => {
    if (sending) return
    setAgentId(nextAgentId)
    setConversationId(undefined)
    setMessages([])
    setShowHistory(false)
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
      setShowHistory(false)
    } catch {
      message.error('历史对话加载失败')
    }
  }

  const send = async () => {
    const question = input.trim()
    if (!question || !agentId || sending) return

    const pendingId = createId()
    setMessages(previous => [
      ...previous,
      { id: createId(), role: 'user', content: question },
      { id: pendingId, role: 'assistant', content: '', pending: true },
    ])
    setInput('')
    setSending(true)

    try {
      const response = await fetch('/api/v1/user/chat/stream', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_id: agentId, question, conversation_id: conversationId }),
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
        if (kind === 'delta') {
          setMessages(previous => previous.map(item => item.id === pendingId
            ? { ...item, pending: false, content: item.content + (data.content || '') }
            : item))
        } else if (kind === 'done') {
          completed = true
          setConversationId(data.conversation_id)
          setRemainingToday(typeof data.remaining_today === 'number' ? data.remaining_today : remainingToday)
          setMessages(previous => previous.map(item => item.id === pendingId
            ? { ...item, pending: false, sources: data.sources || [] }
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

  return <main className="user-page">
    <header className="user-header">
      <div><Title level={3}>智答助手</Title><Text>基于授权知识库，为你提供可靠回答</Text></div>
      <div><Button icon={<HistoryOutlined />} onClick={() => setShowHistory(value => !value)}>历史</Button><Button icon={<PlusOutlined />} onClick={() => { if (!sending) { setConversationId(undefined); setMessages([]); setShowHistory(false) } }}>新对话</Button><Button type="text" aria-label="退出登录" icon={<LogoutOutlined />} onClick={() => void logout()} /></div>
    </header>

    <section className="user-agents" aria-label="已授权 Agent">
      {agents.map(item => <button type="button" key={item.id} className={item.id === agentId ? 'active' : ''} onClick={() => selectAgent(item.id)}>
        <b>{item.avatar || item.name.slice(0, 1)}</b><span>{item.name}<small>{item.description || '专属知识助手'}</small></span>
      </button>)}
    </section>

    {showHistory && <section className="user-history">
      {conversations.length
        ? conversations.map(item => <button type="button" key={item.id} onClick={() => void openConversation(item)}><span>{item.title}</span><small>{agents.find(agent => agent.id === item.agent_id)?.name || '助手'}</small></button>)
        : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无历史对话" />}
    </section>}

    <section className="user-chat">
      <div className="user-chat-title">{selectedAgent?.name || '请选择助手'}<Text type="secondary">{selectedAgent?.description || '请选择一个已授权的 Agent 开始对话。'}</Text></div>
      <div className="user-messages">
        {!messages.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={agentId ? '有什么想了解的？' : '暂无可用助手'} />}
        {messages.map(item => <article key={item.id} className={`user-message ${item.role}`}>
          <div>{item.role === 'user' ? '我' : 'AI'}</div>
          <section>{item.pending ? <Spin size="small" /> : <span>{item.content}</span>}
            {!!item.sources?.length && <footer>{[...new Set(item.sources.map(source => source.metadata?.filename || source.document_name).filter(Boolean))].map(name => <Tag key={name}>{name}</Tag>)}</footer>}
          </section>
        </article>)}
        <div ref={bottomRef} />
      </div>
      <div className="user-composer">
        <div className="user-composer-input">{remainingToday !== null && <small>今日剩余 {remainingToday} 次</small>}<textarea value={input} onChange={event => setInput(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) { event.preventDefault(); void send() } }} placeholder="输入问题；Enter 换行，Ctrl/Cmd + Enter 发送" disabled={!agentId || sending} rows={2} /></div>
        <Button type="primary" icon={<SendOutlined />} disabled={!input.trim() || sending || !agentId} loading={sending} onClick={() => void send()}>发送</Button>
      </div>
    </section>
  </main>
}
