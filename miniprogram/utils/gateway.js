const routes = {
  me: { method: 'GET', path: '/api/v1/miniapp/me' },
  claimInvite: { method: 'POST', path: '/api/v1/miniapp/invite/claim' },
  agents: { method: 'GET', path: '/api/v1/miniapp/agents' },
  sessions: { method: 'GET', path: '/api/v1/miniapp/sessions' },
  sessionMessages: { method: 'GET', path: (data) => `/api/v1/miniapp/sessions/${encodeURIComponent(data.session_id)}/messages` },
  createSession: { method: 'POST', path: '/api/v1/miniapp/sessions' },
  ask: { method: 'POST', path: '/api/v1/miniapp/ask' },
  streamPoll: { method: 'GET', path: (data) => `/api/v1/miniapp/streams/${encodeURIComponent(data.stream_id)}?cursor=${encodeURIComponent(data.cursor || 0)}` },
}

function callLocalGateway(action, data) {
  const localDev = getApp().globalData.localDev
  const route = routes[action]
  if (!route) return Promise.reject(new Error('本地模式不支持该操作'))
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${localDev.baseUrl}${typeof route.path === 'function' ? route.path(data || {}) : route.path}`,
      method: route.method,
      data: route.method === 'GET' ? undefined : data,
      header: { 'X-Miniapp-Dev-Openid': localDev.openid },
      success(response) {
        if (response.statusCode >= 400) return reject(new Error(response.data?.detail || '本地后端请求失败'))
        resolve(response.data)
      },
      fail(error) { reject(new Error(error.errMsg || '无法连接本地后端')) },
    })
  })
}

export function callGateway(action, data = {}) {
  if (getApp().globalData.localDev.enabled) return callLocalGateway(action, data)
  return wx.cloud.callFunction({ name: 'gateway', data: { action, data } })
    .then((response) => {
      const result = response.result || {}
      if (!result.ok) throw new Error(result.message || '请求失败')
      return result.data
    })
}
