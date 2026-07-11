import { callGateway } from '../../utils/gateway'

Page({
  data: { agents: [] },
  async onShow() {
    wx.showLoading({ title: '加载中' })
    try { this.setData({ agents: await callGateway('agents') }) }
    catch (error) { wx.showToast({ title: error.message || '加载失败', icon: 'none' }) }
    finally { wx.hideLoading() }
  },
  openAgent(event) {
    const { id, name } = event.currentTarget.dataset
    wx.navigateTo({ url: `/pages/chat/index?agentId=${id}&name=${encodeURIComponent(name)}` })
  },
})
