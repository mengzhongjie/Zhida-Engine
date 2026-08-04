import { callGateway } from '../../utils/gateway'

Page({
  data: { agents: [], refreshing: false },

  onShow() {
    this.loadAgents()
  },

  /**
   * 下拉刷新（需要在 app.json 中启用 "enablePullDownRefresh": true）
   */
  async onPullDownRefresh() {
    this.setData({ refreshing: true })
    await this.loadAgents()
    wx.stopPullDownRefresh()
    this.setData({ refreshing: false })
  },

  async loadAgents() {
    wx.showLoading({ title: '加载中' })
    try {
      const agents = await callGateway('agents')
      this.setData({ agents })
    } catch (error) {
      wx.showToast({ title: error.message || '加载失败', icon: 'none' })
    } finally {
      wx.hideLoading()
    }
  },

  openAgent(event) {
    const { id, name } = event.currentTarget.dataset
    wx.navigateTo({ url: `/pages/chat/index?agentId=${id}&name=${encodeURIComponent(name)}` })
  },

  openHistory() {
    wx.navigateTo({ url: '/pages/sessions/index' })
  },

})
