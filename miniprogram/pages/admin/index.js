import { callGateway } from '../../utils/gateway'

Page({
  async scan() {
    try {
      const result = await wx.scanCode({ onlyFromCamera: false, scanType: ['qrCode'] })
      const match = /^zhida-admin:([A-Za-z0-9_-]+)$/.exec(result.result || '')
      if (!match) return wx.showToast({ title: '不是有效的智答后台二维码', icon: 'none' })
      await callGateway('adminConfirm', { ticket_id: match[1] })
      wx.showToast({ title: '登录已确认', icon: 'success' })
    } catch (error) {
      wx.showToast({ title: error.message || '确认失败', icon: 'none' })
    }
  },
})
