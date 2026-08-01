import { callGateway } from '../../utils/gateway'

function parseMarkdown(markdown = '') {
  const blocks = []
  const lines = markdown.replace(/\r\n/g, '\n').split('\n')
  let codeLines = []
  let inCode = false
  let paragraph = []

  const flushParagraph = () => {
    const text = paragraph.join('\n').trim()
    if (text) blocks.push({ type: 'paragraph', text })
    paragraph = []
  }

  for (const line of lines) {
    if (line.trim().startsWith('```')) {
      flushParagraph()
      if (inCode) {
        blocks.push({ type: 'code', text: codeLines.join('\n') })
        codeLines = []
      }
      inCode = !inCode
      continue
    }
    if (inCode) {
      codeLines.push(line)
      continue
    }
    const heading = line.match(/^(#{1,3})\s+(.+)$/)
    const bullet = line.match(/^\s*[-*+]\s+(.+)$/)
    const ordered = line.match(/^\s*\d+[.)]\s+(.+)$/)
    if (heading) {
      flushParagraph()
      blocks.push({ type: `heading${heading[1].length}`, text: heading[2] })
    } else if (bullet || ordered) {
      flushParagraph()
      blocks.push({ type: 'list', text: bullet ? bullet[1] : ordered[1], ordered: Boolean(ordered) })
    } else if (!line.trim()) {
      flushParagraph()
    } else {
      paragraph.push(line)
    }
  }
  if (inCode && codeLines.length) blocks.push({ type: 'code', text: codeLines.join('\n') })
  flushParagraph()
  return blocks
}

Page({
  data: {
    agentId: 0,
    navTitle: '智答助手',
    question: '',
    sessionId: '',
    messages: [],
    scrollToId: '',
    loadingAnswer: false,
    loadingHistory: true,
    remainingToday: null,
    initialSessionId: '',
    typingIndex: 0,
  },
  typingTimer: null,

  onLoad(query) {
    const name = decodeURIComponent(query.name || '智答助手')
    this.setData({
      agentId: Number(query.agentId),
      navTitle: name,
      initialSessionId: query.sessionId || '',
    })
    wx.setNavigationBarTitle({ title: name })
    this.restoreLatestSession()
  },

  onUnload() {
    if (this.typingTimer) clearInterval(this.typingTimer)
  },

  goBack() {
    if (this.data.loadingAnswer) {
      wx.showToast({ title: '正在生成回答，请稍候', icon: 'none' })
      return
    }
    wx.navigateBack()
  },

  async restoreLatestSession() {
    try {
      const [sessions, user] = await Promise.all([
        callGateway('sessions'),
        callGateway('me'),
      ])
      const session = this.data.initialSessionId
        ? sessions.find((item) => item.id === this.data.initialSessionId && Number(item.agent_id) === this.data.agentId)
        : sessions.find((item) => Number(item.agent_id) === this.data.agentId)
      if (!session) {
        this.setData({ loadingHistory: false, remainingToday: user.remaining_today })
        return
      }
      const history = await callGateway('sessionMessages', { session_id: session.id })
      const messages = []
      history.forEach((item) => {
        messages.push({ role: 'user', content: item.question })
        messages.push({
          role: 'assistant',
          content: item.answer || '',
          blocks: parseMarkdown(item.answer || ''),
          sources: Array.isArray(item.sources) ? item.sources : [],
        })
      })
      this.setData({
        sessionId: session.id,
        messages,
        remainingToday: user.remaining_today,
        loadingHistory: false,
      })
      this.scrollToBottom()
    } catch (error) {
      this.setData({ loadingHistory: false })
      wx.showToast({ title: error.message || '历史会话加载失败', icon: 'none' })
    }
  },

  startNewChat() {
    if (this.data.loadingAnswer) return
    const reset = () => this.setData({ sessionId: '', initialSessionId: '', messages: [], question: '' })
    if (!this.data.messages.length) return reset()
    wx.showModal({
      title: '开始新对话？',
      content: '当前对话会保留在历史记录中。',
      confirmText: '新对话',
      success: (result) => { if (result.confirm) reset() },
    })
  },

  onInput(event) {
    this.setData({ question: event.detail.value })
  },

  async ask() {
    if (this.data.loadingAnswer || this.data.loadingHistory) return
    const question = this.data.question.trim()
    if (!question) return

    const userMessage = { role: 'user', content: question }
    const assistantMessage = { role: 'assistant', content: '' }
    this.setData({
      question: '',
      messages: [...this.data.messages, userMessage, assistantMessage],
      loadingAnswer: true,
    })
    this.scrollToBottom()

    try {
      const data = await callGateway('ask', {
        agent_id: this.data.agentId,
        question,
        session_id: this.data.sessionId || undefined,
      })

      const answer = data.answer || ''
      const idx = this.data.messages.length - 1

      // 更新 sessionId
      this.setData({
        sessionId: data.session_id || this.data.sessionId,
        remainingToday: data.remaining_today,
      })

      this.startTyping(idx, answer, data.sources || [])
    } catch (error) {
      const idx = this.data.messages.length - 1
      const msgs = this.data.messages
      msgs[idx].content = error.message || '回答失败，请稍后重试'
      this.setData({ messages: msgs, loadingAnswer: false })
    }
  },

  startTyping(msgIndex, fullText, sources = []) {
    if (!fullText) {
      const msgs = [...this.data.messages]
      msgs[msgIndex].content = '暂时没有生成有效回答，请稍后重试。'
      this.setData({ messages: msgs, loadingAnswer: false })
      return
    }
    this.setData({ loadingAnswer: false })
    let pos = 0
    const step = 3

    if (this.typingTimer) clearInterval(this.typingTimer)

    this.typingTimer = setInterval(() => {
      pos += step
      const isFinished = pos >= fullText.length
      if (isFinished) {
        pos = fullText.length
        clearInterval(this.typingTimer)
        this.typingTimer = null
      }
      const msgs = this.data.messages
      const visibleText = fullText.substring(0, pos)
      msgs[msgIndex].content = visibleText
      msgs[msgIndex].showCursor = !isFinished
      // 流式显示期间也解析已经完整到达的段落，避免换行与列表直到结束才突然合并。
      // 对未闭合的 Markdown，解析器会按普通段落安全展示。
      msgs[msgIndex].blocks = parseMarkdown(visibleText)
      if (isFinished) {
        msgs[msgIndex].sources = sources
      }
      this.setData({ messages: msgs, typingIndex: pos })
      this.scrollToBottom()
    }, 30)
  },

  scrollToBottom() {
    const msgs = this.data.messages
    const lastIdx = msgs.length - 1
    if (lastIdx >= 0) {
      this.setData({ scrollToId: `msg-${lastIdx}` })
    }
  },
})
