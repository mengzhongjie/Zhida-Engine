import { callGateway } from '../../utils/gateway'

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
    wx.navigateBack()
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
      this.startTyping(idx, answer)
    } catch (error) {
      const idx = this.data.messages.length - 1
      const msgs = this.data.messages
      msgs[idx].content = error.message || '回答失败，请稍后重试'
      this.setData({ messages: msgs, loadingAnswer: false })
    }
  },

  startTyping(msgIndex, fullText) {
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
