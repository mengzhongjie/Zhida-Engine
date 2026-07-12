import { callGateway } from '../../utils/gateway'

Page({
  data: { agents: [], inviteCode: '', redeeming: false, refreshing: false },

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

  onInviteInput(event) {
    this.setData({ inviteCode: event.detail.value })
  },

  async redeemInvite() {
    const inviteCode = this.data.inviteCode.trim()
    if (!inviteCode) return wx.showToast({ title: '请输入邀请码', icon: 'none' })
    this.setData({ redeeming: true })
    try {
      const user = await callGateway('claimInvite', { invite_code: inviteCode })
      this.setData({ inviteCode: '' })
      wx.showToast({ title: `额度已更新：${user.daily_question_limit}/天`, icon: 'none' })
    } catch (error) {
      wx.showToast({ title: error.message || '邀请码无效', icon: 'none' })
    } finally {
      this.setData({ redeeming: false })
    }
  },
})
