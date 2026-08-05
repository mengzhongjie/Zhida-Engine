/**
 * 显式声明 PostCSS 配置。
 *
 * 项目没有额外 PostCSS 插件；保留这个文件可避免 Vite 在开发热更新时
 * 继续从 package.json 搜索配置并被中断写入的 JSON 影响。
 */
module.exports = {
  plugins: {},
}
