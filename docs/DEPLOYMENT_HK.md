# 香港服务器部署

本方案面向 2 核 2GB 的香港 ECS/轻量服务器：模型、向量化和视觉识别均使用云端 API；服务端只运行 FastAPI、SQLite、Chroma 和 Nginx。

## 部署前准备

- 两个域名：`admin.example.com`（管理端）与 `app.example.com`（用户端）
- 两个域名 A 记录均解析至服务器公网 IP
- 放通安全组 TCP `80`、`443`、`22`；不要放通 `18900`、`5173`、`5174`
- 安装 Docker Engine、Docker Compose plugin 和 Nginx

## 首次部署

```bash
git clone <你的仓库地址> /opt/zhida-engine
cd /opt/zhida-engine
cp .env.production.example .env
openssl rand -base64 48
```

将最后一条命令的输出写入 `.env` 的 `ZHIDA_AUTH_SESSION_SECRET`，并填入两个真实域名。`.env` 和 `data/` 都不能提交或上传到公开仓库。

先签发证书（域名必须已经解析，且 80 端口未被其他服务占用）：

```bash
sudo systemctl stop nginx
sudo certbot certonly --standalone -d admin.example.com -d app.example.com
```

将 `deploy/nginx/zhida-engine.conf.template` 复制为 `/etc/nginx/sites-available/zhida-engine`，替换域名后启用并检查：

```bash
sudo ln -s /etc/nginx/sites-available/zhida-engine /etc/nginx/sites-enabled/zhida-engine
sudo nginx -t
sudo systemctl reload nginx
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:18900/health
```

首次访问 `https://admin.example.com`，完成唯一管理员注册；之后使用管理端创建 Agent、配置模型并发放用户激活码。生产环境不设置默认管理员密码。

## 更新程序

配置、知识库、管理员和激活码都在 `./data/` 中；更新前先备份它。

```bash
cd /opt/zhida-engine
tar -czf ../zhida-data-$(date +%F-%H%M).tgz data
git pull --ff-only
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:18900/health
```

仅修改管理台中的模型、Agent 或知识库时，不需要执行上述代码更新。

## 运行检查与回滚

```bash
docker compose logs --tail=200 zhida-engine
docker compose restart zhida-engine
```

代码更新失败时回退到上一个 Git 提交后重新构建；数据异常时停止服务，再从备份恢复 `data/`。不要在容器运行时直接复制 SQLite 数据库文件。
