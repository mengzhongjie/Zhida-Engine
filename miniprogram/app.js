App({
  globalData: {
    user: null,
    // 当前为本地联调模式；正式发布前必须改为 false，恢复 CloudBase gateway 云函数。
    localDev: {
      enabled: true,
      baseUrl: 'http://127.0.0.1:18900',
      openid: 'local-wechat-test-user',
    },
  },
  onLaunch() {
    if (this.globalData.localDev.enabled) return
    wx.cloud.init({
      // 在微信开发者工具中替换为实际 CloudBase 环境 ID。
      env: 'YOUR_CLOUDBASE_ENV_ID',
      traceUser: true,
    })
  },
})
