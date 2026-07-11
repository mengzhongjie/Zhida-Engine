import { callGateway } from '../../utils/gateway'

Page({
  data: { agentId: 0, question: '', sessionId: '', messages: [] },
  onLoad(query) {
    this.setData({ agentId: Number(query.agentId) })
    wx.setNavigationBarTitle({ title: decodeURIComponent(query.name || '智答助手') })
  },
  onInput(event) { this.setData({ question: event.detail.value }) },
  async ask() {
    const question = this.data.question.trim()
    if (!question) return
    this.setData({ question: '', messages: [...this.data.messages, { role: 'user', content: question }] })
    wx.showLoading({ title: '思考中' })
    try {
      const data = await callGateway('ask', { agent_id: this.data.agentId, question, session_id: this.data.sessionId || undefined })
      this.setData({ sessionId: data.session_id, messages: [...this.data.messages, { role: 'assistant', content: data.answer }] })
    } catch (error) {
      wx.showToast({ title: error.message || '回答失败', icon: 'none' })
    } finally { wx.hideLoading() }
  },
})
