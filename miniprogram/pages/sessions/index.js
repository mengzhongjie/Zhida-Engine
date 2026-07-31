import { callGateway } from '../../utils/gateway'

function formatTime(value) {
  if (!value) return ''
  const date = new Date(value)
  const pad = (number) => String(number).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

Page({
  data: { sessions: [], loading: true },

  onShow() {
    this.loadSessions()
  },

  async loadSessions() {
    this.setData({ loading: true })
    try {
      const [sessions, agents] = await Promise.all([
        callGateway('sessions'),
        callGateway('agents'),
      ])
      const agentMap = {}
      agents.forEach((agent) => { agentMap[agent.id] = agent })
      this.setData({
        sessions: sessions.map((session) => ({
          ...session,
          agentName: agentMap[session.agent_id]?.name || '智答助手',
          displayTime: formatTime(session.updated_at),
        })),
      })
    } catch (error) {
      wx.showToast({ title: error.message || '历史对话加载失败', icon: 'none' })
    } finally {
      this.setData({ loading: false })
    }
  },

  openSession(event) {
    const { id, agentId, name } = event.currentTarget.dataset
    wx.navigateTo({
      url: `/pages/chat/index?agentId=${agentId}&sessionId=${encodeURIComponent(id)}&name=${encodeURIComponent(name)}`,
    })
  },
})
