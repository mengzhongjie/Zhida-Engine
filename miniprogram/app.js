App({
  globalData: { user: null },
  onLaunch() {
    wx.cloud.init({
      // 在微信开发者工具中替换为实际 CloudBase 环境 ID。
      env: 'YOUR_CLOUDBASE_ENV_ID',
      traceUser: true,
    })
  },
})
