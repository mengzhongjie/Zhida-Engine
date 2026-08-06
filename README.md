# 智答引擎（ZhiDa Engine）

> 基于 RAG 架构的个人 AI 知识助手，通过内置管理台提供知识问答与运营管理。

---

## 目录

- [功能特性](#功能特性)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [项目结构](#项目结构)
- [配置说明](#配置说明)
- [作为服务接入其他应用](#作为服务接入其他应用)
- [API 文档](#api-文档)
- [架构说明](#架构说明)

---

## 功能特性

- **📚 知识库管理** — 上传 PDF/DOCX/Excel/MD/TXT/CSV/JSON 等文档，自动解析、切分、向量化
- **🔍 RAG 问答** — 基于混合检索（向量 + 关键词）的智能问答，支持来源引用
- **🤖 Agent 管理** — 创建 AI 助手，绑定知识库和 LLM 配置
- **💬 管理台对话** — 选择已启用 Agent，直接使用其知识库进行对话
- **🔐 网页访问控制** — 管理员使用账号、密码和图形验证码登录；用户使用受 Agent 授权的一次性激活码登录
- **🧠 长期记忆** — 基于 Mem0 的跨会话个性化记忆
- **🔒 格式校验** — 上传文件自动检测真实类型，防止扩展名伪装，确保数据安全
- **⚡ 可选 MinerU 解析** — 可选集成 MinerU 引擎，支持复杂 PDF 布局/OCR/公式识别

---

## 技术栈

### 后端

| 组件 | 技术选型 |
|------|----------|
| 框架 | Python 3.11+ / FastAPI / SQLAlchemy (async) |
| 数据库 | SQLite（aiosqlite） |
| 向量数据库 | ChromaDB（嵌入式） |
| 嵌入模型 | 云端 Embedding API（OpenAI 兼容） |
| LLM 网关 | litellm + OpenAI 兼容客户端（云端厂商模板 + 自定义） |
| 缓存 | diskcache（基于 SQLite） |
| 文档解析 | pdfplumber, python-docx, openpyxl, pandas |
| 可选解析 | MinerU（magic-pdf，需额外安装） |
| 中文分词 | jieba |
| 格式校验 | filetype（magic bytes）+ langdetect（语言识别） |

### 前端

| 组件 | 技术选型 |
|------|----------|
| 框架 | React 19 / TypeScript 6 |
| 构建工具 | Vite 8 |
| UI 组件 | Ant Design 6 |
| 部署 | 用户端、管理端分别构建；由 FastAPI 按站点主机名提供 |

---

## 快速开始

### 后端

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

服务启动在 `http://127.0.0.1:18900`，API 文档在 `http://127.0.0.1:18900/api/docs`（仅 debug 模式）。

### 前端（开发模式）

```bash
cd frontend-admin
npm install
npm run dev
# 用户端开发服务器（独立入口）
npm run dev:user
```

管理端开发服务器在 `http://localhost:5173`，用户端在 `http://localhost:5174`；二者均将 API 请求代理到后端 18900 端口。

### 生产构建

```bash
cd frontend-admin
npm run build
# 构建产物分别输出到 backend/static-admin/ 和 backend/static-user/
```

### 公网双站点部署

生产环境应为两个站点配置不同的 HTTPS 主机名，例如 `admin.example.com`（管理端）和 `app.example.com`（用户端）。两站点都反向代理 `/api/` 到同一后端，并保留原始 `Host` 请求头；后端据此提供对应前端。Cookie 使用 host-only 策略，因此用户站不会携带管理员会话 Cookie。

```nginx
location / {
  proxy_pass http://127.0.0.1:18900;
  proxy_set_header Host $host;
  proxy_set_header X-Forwarded-Proto $scheme;
  # 覆盖（不要追加）客户端传入的转发头，避免伪造真实 IP。
  proxy_set_header X-Forwarded-For $remote_addr;
  proxy_set_header X-Real-IP $remote_addr;
}
```

同时在私有 `.env` 中声明两个公网主机名：

```env
ZHIDA_TRUSTED_HOSTS=admin.example.com,app.example.com
ZHIDA_USER_APP_HOSTS=app.example.com
ZHIDA_CORS_ORIGINS=https://admin.example.com,https://app.example.com
ZHIDA_AUTH_REQUIRE_HTTPS=true
# Docker 内由宿主机 Nginx 转发时，通常为 172.17.0.1；以实际容器日志看到的代理 IP 为准。
ZHIDA_TRUSTED_PROXY_IPS=127.0.0.1,::1,172.17.0.1
```

必须在 HTTPS 后运行；公网 HTTP 请求会被拒绝，认证 Cookie 使用 `HttpOnly + Secure + SameSite=Strict`，并在 HTTPS 响应中下发 HSTS。反向代理必须保留 `Host` 并传递 `X-Forwarded-Proto`，否则后端无法正确判断安全连接。

### Docker 部署

```bash
docker compose up -d
```

面向香港/海外服务器的双域名 HTTPS 部署、Nginx 配置、数据备份与更新流程见 [部署说明](docs/DEPLOYMENT_HK.md)。

---

## 项目结构

```
.
├── backend/
│   ├── main.py                     # 应用入口
│   ├── requirements.txt
│   ├── app/
│   │   ├── core/                   # 核心配置/安全/数据库
│   │   │   ├── config.py           # Pydantic Settings（环境变量 + .env）
│   │   │   ├── database.py         # SQLAlchemy 异步引擎
│   │   │   ├── security.py         # 加密/进程锁/权限
│   │   │   └── resource_manager.py # 资源管理器
│   │   ├── models/                 # ORM 模型
│   │   ├── schemas/                # Pydantic Schema
│   │   ├── api/v1/                 # API 路由
│   │   │   ├── knowledge/          # 知识库
│   │   │   ├── agent/              # Agent
│   │   │   ├── channel/            # 渠道
│   │   │   ├── config/             # LLM 配置
│   │   │   ├── embedding/          # 向量化配置
│   │   │   ├── qa/                 # 问答
│   │   │   └── admin/              # 系统管理
│   │   └── services/               # 服务层
│   │       ├── knowledge/          # 文档解析/切片/向量化/索引
│   │       │   ├── parser.py       # DocumentParser（含 MinerU 策略）
│   │       │   ├── splitter.py     # TextSplitter（父子块切分）
│   │       │   ├── embedder.py     # EmbeddingService
│   │       │   ├── indexer.py      # IndexManager -> ChromaDB
│   │       │   └── mineru/         # MinerU 可选解析
│   │       │       ├── config.py   # MinerUConfig
│   │       │       ├── backend.py  # Embedded/Http 后端
│   │       │       └── parser.py   # MinerUParser
│   │       ├── validation/         # 格式校验模块
│   │       │   ├── config.py       # ValidationConfig
│   │       │   ├── file_validator.py # magic bytes 检测
│   │       │   ├── precheck.py     # 上传前预检
│   │       │   └── quality_checker.py # 解析后质检
│   │       ├── llm/                # LLM 网关
│   │       ├── qa/                 # 问答服务
│   │       ├── memory/             # Mem0 记忆层
│   │       └── cache/              # 缓存服务
│   └── tests/
├── frontend-admin/                 # React 管理后台
├── docs/
├── API_DOCS.md
├── ARCHITECTURE.md
├── CLAUDE.md
└── Dockerfile
```

---

## 配置说明

配置通过环境变量（`ZHIDA_` 前缀）+ `.env` 文件管理。关键配置项：

### 格式校验

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ZHIDA_ENABLE_FORMAT_CHECK` | `true` | 总开关 |
| `ZHIDA_FORMAT_CHECK_STRICT` | `true` | 严格模式 |
| `ZHIDA_FORMAT_MIN_TEXT_LENGTH` | `10` | 最小文本长度 |
| `ZHIDA_FORMAT_GARBAGE_THRESHOLD` | `0.5` | 乱码阈值 |
| `ZHIDA_FORMAT_AUTO_REJECT_EMPTY` | `true` | 空结果自动拒绝 |

### MinerU（可选）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ZHIDA_ENABLE_MINERU` | `false` | 总开关 |
| `ZHIDA_MINERU_MODE` | `embedded` | embedded / service |
| `ZHIDA_MINERU_FORMATS` | `pdf` | 处理格式 |
| `ZHIDA_MINERU_SERVICE_URL` | `http://127.0.0.1:18901` | 服务地址 |

### 模块开关

```python
ENABLE_SINGLE_FLIGHT      # 幂等请求合并
ENABLE_STREAMING          # 流式输出
ENABLE_SOURCE_CITATION    # 来源引用
```

### 网页登录与兑换码

生产环境不提供默认管理员账号或密码。首次访问管理端时注册唯一管理员；后续由管理员创建一次性激活码给用户使用。认证密钥和域名配置应写入不提交 Git 的根目录 `.env`，可从 `.env.production.example` 复制。

```env
ZHIDA_AUTH_SESSION_SECRET=请设置至少32位随机字符串
ZHIDA_USER_APP_HOSTS=app.example.com
ZHIDA_TRUSTED_HOSTS=admin.example.com,app.example.com
ZHIDA_CORS_ORIGINS=https://admin.example.com,https://app.example.com
```

> 安全提示：根目录 `.env` 已被 Git 忽略，不应将实际管理员凭据提交到仓库或写入公开文档。部署到公网前请使用唯一的强密码与认证密钥。

管理员通过 `POST /api/v1/auth/admin/access-codes` 创建一次性激活码并指定可访问的 Agent。激活码在用户首次登录后立即变为“已激活”，完整码密文会被销毁，无法被管理员再次复制、也无法被第二个人用于登录。每个激活码只绑定一个匿名用户身份，因此历史会话、长期记忆和每日额度不会在不同持码人之间共享。

会话使用 `HttpOnly + Secure + SameSite=Strict` Cookie。管理员默认有效期为 8 小时、用户默认为 7 天；在剩余有效期低于完整周期三分之一时，正常请求会触发一次滑动续期。用户清除浏览器数据或长期未访问导致 Cookie 失效时，管理员可在管理台“重置登录”换发一枚新的单次激活码；旧设备会立即下线，用户历史仍保留。停用、过期、删除访问资格或退出登录都会立即阻断后续会话；删除会同时清理该用户的会话与问答记录。

---

## API 文档

完整的 API 文档参见 [API_DOCS.md](API_DOCS.md)。

核心端点：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/knowledge/bases` | GET/POST | 知识库 CRUD |
| `/api/v1/knowledge/bases/{kb_id}/upload` | POST | 文档上传（含格式校验）|
| `/api/v1/knowledge/documents/{id}` | DELETE | 删除文档 |
| `/api/v1/agents` | GET/POST | Agent CRUD |
| `/api/v1/agents/{id}/start` | POST | 启动 Agent |
| `/api/v1/channels` | GET/POST | 渠道配置 |
| `/api/v1/channels/{type}/login/qrcode` | POST | 生成登录二维码 |
| `/api/v1/qa/ask` | POST | 提问 |
| `/api/v1/admin/settings` | GET/PUT | 系统设置 |

---

## 作为服务接入其他应用

智答引擎可以作为一个独立的本地 RAG 服务，被 Web 应用、桌面端、企业内部工具或其他 AI Agent 调用。调用方只需要保存 `agent_id`；该 Agent 已挂载的所有知识库会一起参与检索。

### 1. 启动与健康检查

默认服务仅监听本机回环地址，适合桌面端或同机应用接入：

```bash
cd backend
source .venv/bin/activate
python main.py

curl http://127.0.0.1:18900/health
```

若要供其他机器访问，请通过反向代理或受控网关暴露服务，并自行增加调用方认证、HTTPS、IP 白名单和请求审计。不要直接将当前桌面默认端口公开到互联网。

### 2. 最小接入流程

```text
创建知识库 → 上传/导入资料 → 创建 Agent → 挂载知识库 → 启动 Agent → 调用问答接口
```

同一个知识库可以挂载给多个 Agent；一个 Agent 也可以挂载多个知识库。

```bash
# 创建 Agent（新建后默认停用）
curl -X POST http://127.0.0.1:18900/api/v1/agents \
  -H 'Content-Type: application/json' \
  -d '{"name":"产品知识助手","description":"回答产品与交付问题"}'

# 将已有知识库 12 挂载到 Agent 3
curl -X POST http://127.0.0.1:18900/api/v1/knowledge/bases/12/attach \
  -H 'Content-Type: application/json' \
  -d '{"agent_id":3}'

# 启动：启动后即可在管理台对话页和外部问答 API 中使用
curl -X POST http://127.0.0.1:18900/api/v1/agents/3/start
```

### 3. 调用 RAG 问答

`POST /api/v1/qa/ask` 是其他应用最常用的接口。它会执行混合检索、父块扩展、回答生成与来源整理，并返回本轮使用的模型和文档来源。

```bash
curl -X POST http://127.0.0.1:18900/api/v1/qa/ask \
  -H 'Content-Type: application/json' \
  -d '{
    "agent_id": 3,
    "question": "退款流程是什么？",
    "user_id": "external-user-42",
    "chat_id": "web-session-a8f2",
    "chat_type": "private"
  }'
```

响应示例：

```json
{
  "question": "退款流程是什么？",
  "answer": "……",
  "sources": [
    {
      "document_name": "售后政策.md",
      "chunk_text": "……",
      "score": 0.82,
      "source_type": "document"
    }
  ],
  "confidence": 0.8,
  "response_time_ms": 684.2,
  "model_used": "your-model-name",
  "from_cache": false
}
```

JavaScript 调用示例：

```ts
const response = await fetch('http://127.0.0.1:18900/api/v1/qa/ask', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    agent_id: 3,
    question: userQuestion,
    user_id: currentUserId,
    chat_id: currentConversationId,
    chat_type: 'private',
  }),
})
const result = await response.json()
```

`user_id` 和 `chat_id` 建议由接入方稳定传入：它们用于问答历史、长期记忆隔离与可观测性关联。调用方应将 `sources` 原样保留或展示，避免把 RAG 回答误呈现为无来源结论。

### 4. 为调用方补充知识

本地文件使用 `multipart/form-data` 上传，接口会立即返回文档任务；解析和向量化在后台执行。通过 `GET /api/v1/knowledge/documents?kb_id={kb_id}` 查询 `status`，直到为 `completed` 后再作为稳定知识参与问答。

```bash
curl -X POST http://127.0.0.1:18900/api/v1/knowledge/bases/12/upload \
  -F 'file=@./售后政策.pdf'
```

云文档导入可通过管理台完成。飞书导入会创建后台任务并在知识库详情页显示逐篇进度；同一正文基于 SHA-256 自动去重。

### 5. 接入边界

- 问答接口只接受已启用的 Agent；停止 Agent 后，调用会返回“Agent 不存在或未启用”。
- `/api/v1/qa/ask` 当前返回完整 JSON 回答；外部应用需要打字机效果时，应在自身 UI 层按段或按字展示 `answer`。
- 桌面管理 API 默认没有面向公网的多租户鉴权设计。接入第三方应用前，应由宿主应用或网关负责身份认证、授权和限流。
- API Key、飞书密钥等只在本机加密保存；接入方不应从 API 或日志中读取、传递这些密钥。

---

## 架构说明

完整的架构设计参见 [ARCHITECTURE.md](ARCHITECTURE.md)。

### 文档解析流程

```
上传文件 → magic bytes 校验 → 解析（MinerU / 本地）→ 质量检查 → 父子块切分 → 向量化 → ChromaDB
```

### MinerU 集成（可选）

MinerU 是上海 AI Lab 开源的一站式文档解析引擎，支持复杂 PDF 布局检测、OCR、LaTeX 公式识别和 HTML 表格还原。

两种部署模式：
- **嵌入式**：`pip install magic-pdf`，直接调用 Python API
- **HTTP 服务**：Docker 运行 `opendatalab/mineru:latest`，通过 REST API 调用

MinerU 不可用时自动降级到本地解析器。

### 格式校验

所有上传文件经过三层检查：
1. **Magic bytes** — 文件头字节匹配真实类型（无需信任扩展名）
2. **文件名清洗** — 移除路径穿越和危险字符
3. **质量评分** — 解析结果的空/乱码/完整度/语言/结构多维评分

---

## 许可证

AGPL-3.0
