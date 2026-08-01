# 邀请制小程序部署

## 低成本部署

1. 在阿里云轻量服务器安装 Docker 与 Docker Compose，将仓库上传至服务器。
2. 复制 `.env.example` 为 `.env`，填写随机网关密钥、管理员 OpenID、HTTPS 域名对应的 `ZHIDA_TRUSTED_HOSTS` 和 `ZHIDA_CORS_ORIGINS`；不要将此文件提交到 Git。
3. 配置云端 Embedding 和 LLM：首次用管理员扫码登录后台，在“设置”中填写 API Key。低配服务器不要启用本地 embedding 模型。
4. 执行 `docker compose up -d --build`。应用数据位于 `./data`，包含 SQLite、Chroma、缓存和日志。
5. 使用 Nginx/Caddy 为 `18900` 提供 HTTPS 反向代理，应用端口保持绑定到 `127.0.0.1`，不要在安全组中直接暴露。CloudBase 云函数的 `BACKEND_BASE_URL` 必须是该 HTTPS 域名。

## CloudBase

在微信开发者工具导入 `miniprogram/`，将 `app.js` 的 `YOUR_CLOUDBASE_ENV_ID` 替换为实际环境 ID。部署 `cloudfunctions/gateway`，并配置两个云函数环境变量：

- `BACKEND_BASE_URL=https://你的域名`
- `MINIPROGRAM_GATEWAY_SECRET`：与服务器 `.env` 完全一致

管理员在小程序进入 `pages/admin/index` 后扫描网页后台二维码确认登录。管理员 OpenID 由 `.env` 的 `ZHIDA_ADMIN_OPENIDS` 控制。

## 备份

每天打包 `data/zhida_engine.db`、`data/chroma_db/` 与上传文档目录，再上传到对象存储。保留至少 7 天；恢复时停止容器、还原 `data/` 后重新启动。

## 安全边界

生产环境必须保持 `ZHIDA_ADMIN_AUTH_REQUIRED=true`。除 `/api/v1/miniapp/*` 和管理员登录握手外，所有 `/api/v1/*` 都要求管理员短期令牌；小程序 API 仍要求 CloudBase 签名。服务会校验请求 Host 与浏览器 Origin，需与 `.env` 中的域名配置一致。服务器端口只应由 HTTPS 反向代理暴露，必要时在安全组中限制来源。
