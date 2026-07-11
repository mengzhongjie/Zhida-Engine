export function callGateway(action, data = {}) {
  return wx.cloud.callFunction({ name: 'gateway', data: { action, data } })
    .then((response) => {
      const result = response.result || {}
      if (!result.ok) throw new Error(result.message || '请求失败')
      return result.data
    })
}
