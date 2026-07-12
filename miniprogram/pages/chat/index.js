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
    typingIndex: 0,
  },
  typingTimer: null,

  onLoad(query) {
    const name = decodeURIComponent(query.name || '智答助手')
    this.setData({
      agentId: Number(query.agentId),
      navTitle: name,
    })
    wx.setNavigationBarTitle({ title: name })
  },

  onUnload() {
    if (this.typingTimer) clearInterval(this.typingTimer)
  },

  goBack() {
    if (this.data.loadingAnswer) {
      wx.showToast({ title: '正在生成回答，请稍候', icon: 'none' })
      return
    }
    if (!this.data.messages.length) return wx.navigateBack()
    wx.showModal({
      title: '确认退出对话？',
      content: '当前版本为轻量会话，返回后不会自动恢复本次对话上下文。',
      confirmText: '仍要退出',
      cancelText: '继续对话',
      success: (result) => {
        if (result.confirm) wx.navigateBack()
      },
    })
  },

  onInput(event) {
    this.setData({ question: event.detail.value })
  },

  async ask() {
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
      this.setData({ sessionId: data.session_id || this.data.sessionId })

      // 打字机效果
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
      this.setData({ loadingAnswer: false })
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
      msgs[msgIndex].content = fullText.substring(0, pos)
      msgs[msgIndex].showCursor = !isFinished
      if (isFinished) {
        msgs[msgIndex].blocks = parseMarkdown(fullText)
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
