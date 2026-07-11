import { callGateway } from '../../utils/gateway'

Page({
  data: { inviteCode: '' },
  async onShow() {
    try {
      const user = await callGateway('me')
      getApp().globalData.user = user
      wx.reLaunch({ url: '/pages/agents/index' })
    } catch (_) { /* 未激活时留在邀请码页 */ }
  },
  onInput(event) { this.setData({ inviteCode: event.detail.value }) },
  async claim() {
    if (!this.data.inviteCode.trim()) return wx.showToast({ title: '请输入邀请码', icon: 'none' })
    wx.showLoading({ title: '正在验证' })
    try {
      const user = await callGateway('claimInvite', { invite_code: this.data.inviteCode })
      getApp().globalData.user = user
      wx.reLaunch({ url: '/pages/agents/index' })
    } catch (error) {
      wx.showToast({ title: error.message || '邀请码无效', icon: 'none' })
    } finally { wx.hideLoading() }
  },
})
