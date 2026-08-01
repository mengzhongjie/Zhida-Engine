// CloudBase 云函数：获取可信 OpenID，并仅代理允许的小程序 API。
const cloud = require('wx-server-sdk')
const crypto = require('crypto')
const https = require('https')
const http = require('http')

cloud.init({ env: cloud.DYNAMIC_CURRENT_ENV })

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

function requestBackend(route, openid, body) {
  const baseUrl = process.env.BACKEND_BASE_URL
  const secret = process.env.MINIPROGRAM_GATEWAY_SECRET
  if (!baseUrl || !secret) throw new Error('CloudBase 网关环境变量未配置')
  const timestamp = String(Math.floor(Date.now() / 1000))
  const signature = crypto.createHmac('sha256', secret).update(`${timestamp}.${openid}`).digest('hex')
  const path = typeof route.path === 'function' ? route.path(body || {}) : route.path
  const url = new URL(path, baseUrl)
  const payload = route.method === 'GET' ? null : JSON.stringify(body || {})
  return new Promise((resolve, reject) => {
    const client = url.protocol === 'http:' ? http : https
    const req = client.request(url, {
      method: route.method,
      headers: {
        'Content-Type': 'application/json',
        'X-Miniapp-Openid': openid,
        'X-Miniapp-Timestamp': timestamp,
        'X-Miniapp-Signature': signature,
        ...(payload ? { 'Content-Length': Buffer.byteLength(payload) } : {}),
      },
    }, (res) => {
      let data = ''
      res.on('data', (chunk) => { data += chunk })
      res.on('end', () => {
        let parsed
        try { parsed = data ? JSON.parse(data) : {} } catch (_) { parsed = { detail: data } }
        if (res.statusCode >= 400) return reject(new Error(parsed.detail || '后端请求失败'))
        resolve(parsed)
      })
    })
    req.on('error', reject)
    if (payload) req.write(payload)
    req.end()
  })
}

exports.main = async (event) => {
  const route = routes[event.action]
  if (!route) return { ok: false, message: '不支持的操作' }
  const { OPENID } = cloud.getWXContext()
  if (!OPENID) return { ok: false, message: '无法获取微信身份' }
  try {
    return { ok: true, data: await requestBackend(route, OPENID, event.data) }
  } catch (error) {
    return { ok: false, message: error.message || '请求失败' }
  }
}
