# 智答引擎（ZhiDa Engine）

> 基于 RAG 架构的个人 AI 知识助手，通过内置管理台提供知识问答与运营管理。

---

## 目录

- [功能特性](#功能特性)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [项目结构](#项目结构)
- [配置说明](#配置说明)
- [Langfuse 数据集评测](#langfuse-数据集评测)
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
- **🧠 上下文感知会话** — Agent 独立上下文窗口（32-256K），自动问题改写、会话压缩与历史裁剪
- **🧠 长期记忆** — 基于 Mem0 的跨会话个性化记忆
- **🔒 格式校验** — 上传文件自动检测真实类型，防止扩展名伪装，确保数据安全
- **⚡ 可选 MinerU 解析** — 可选集成 MinerU 引擎，支持复杂 PDF 布局/OCR/公式识别
- **🌐 网页/飞书导入** — 从 URL 或飞书云文档导入资料，自动去重
- **📊 可观测与评测** — 可选接入 Langfuse，记录检索与生成全过程；支持按 Agent、知识库和黄金集运行本地或 Langfuse Dataset 实验
- **🔧 开发维护模式** — 一键暂停用户端问答，维护期间不消耗用户额度

---

## 技术栈

### 后端

| 组件 | 技术选型 |
|------|----------|
| 框架 | Python 3.11+ / FastAPI / SQLAlchemy (async) |
| 数据库 | SQLite（aiosqlite） |
| 向量数据库 | ChromaDB（嵌入式） |
| 嵌入模型 | 云端 Embedding API（OpenAI 兼容，多档案管理） |
| LLM 网关 | litellm + OpenAI 兼容客户端（主模型 / 降级 / 上下文三角色） |
| 缓存 | diskcache（基于 SQLite）+ 进程内 L1 |
| 文档解析 | pdfplumber, python-docx, openpyxl, pandas |
| 可选解析 | MinerU（magic-pdf，需额外安装） |
| 中文分词 | jieba |
| 格式校验 | filetype（magic bytes）+ langdetect（语言识别） |
| 可观测性 | Langfuse（可选，云端在线评测） |
| 网络检索 | Tavily / Exa（RAG 未命中补充，可选） |

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
│   │   │   ├── database.py         # SQLAlchemy 异步引擎 + 迁移
│   │   │   ├── security.py         # 加密/进程锁/权限/可信代理
│   │   │   └── resource_manager.py # 资源管理器
│   │   ├── models/                 # ORM 模型（agent/knowledge/llm_config/auth/qa/observability）
│   │   ├── schemas/                # Pydantic Schema
│   │   ├── api/v1/                 # API 路由
│   │   │   ├── auth/               # 认证：管理员注册/登录/激活码/会话
│   │   │   ├── user/               # 用户站：Agent/会话/流式问答/额度
│   │   │   ├── knowledge/          # 知识库
│   │   │   ├── agent/              # Agent
│   │   │   ├── config/             # LLM 配置
│   │   │   ├── embedding/          # 向量化配置
│   │   │   ├── vision/             # 视觉模型配置
│   │   │   ├── qa/                 # 问答
│   │   │   └── admin/              # 系统管理/维护模式/可观测性
│   │   └── services/               # 服务层
│   │       ├── knowledge/          # 文档解析/切片/向量化/索引
│   │       │   ├── parser.py       # DocumentParser（含 MinerU 策略）
│   │       │   ├── splitter.py     # TextSplitter（父子块切分）
│   │       │   ├── embedder.py     # EmbeddingService
│   │       │   ├── indexer.py      # IndexManager -> ChromaDB
│   │       │   └── mineru/         # MinerU 可选解析
│   │       ├── validation/         # 格式校验模块
│   │       ├── llm/                # LLM 网关（主/降级/上下文三角色）
│   │       ├── qa/                 # 问答服务（改写/多路检索/压缩 + Langfuse 观察）
│   │       ├── memory/             # Mem0 记忆层
│   │       └── cache/              # 缓存/请求合并/降级/限流
│   └── tests/
├── frontend-admin/                 # 前端（管理台 + 用户站共用，按 mode 构建）
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

管理端「系统设置 → 功能开关」中可切换，进程内生效（重启后回退到 `.env`）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ZHIDA_ENABLE_STREAMING` | `true` | 流式输出 |
| `ZHIDA_ENABLE_SOURCE_CITATION` | `true` | 来源引用 |
| `ZHIDA_DEVELOPMENT_MODE` | `false` | 开发维护模式：暂停用户端问答（返回 503，不消耗额度） |

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

### 可观测性（Langfuse）

可选接入 Langfuse 记录 RAG 全过程（检索块明细、生成、token 用量），并支持云端在线评测。在管理台「系统设置 → 可观测性」配置，或直接写入环境变量：

```env
ZHIDA_LANGFUSE_ENABLED=true
ZHIDA_LANGFUSE_PUBLIC_KEY=...
ZHIDA_LANGFUSE_SECRET_KEY=...
# 可选：开启云端在线评测（把问题与检索证据提供给云端 Judge 评分）
ZHIDA_LANGFUSE_ONLINE_EVALUATION_ENABLED=false
```

> 安全说明：Langfuse host 固定为 `https://cloud.langfuse.com`，非可信域名拒绝上报；密钥在数据库中加密存储、API 脱敏返回。

`online_evaluation_enabled` 用于常规问答 Trace 的云端评估：启用后，新产生的 `rag-answer` Trace 会包含问题、实际检索证据与最终回答，由 Langfuse 中已启用的 Trace Evaluator 异步评分。它和下面的 Dataset 实验是两条独立链路。

---

## Langfuse 数据集评测

评测以 **Agent + 已挂载知识库 + 该知识库的黄金集** 为边界。黄金题属于知识库，不属于 Agent；Agent 决定实际使用的提示词、模型和已挂载知识库。管理台入口为「Agent 评测」，包括「本地评测」「Langfuse 实验」和「数据集管理」三个页面。

### 两种评测方式

| 方式 | 数据集来源 | 执行位置 | 结果位置 | 适用场景 |
|------|------------|----------|----------|----------|
| 本地评测 | 本地黄金集 | 本机后端 | 管理台运行记录 | 修改黄金题后快速回归 |
| Langfuse 实验 | Langfuse Dataset | 本机后端实际调用 Agent/RAG | 管理台运行记录 + Langfuse Experiment | 跨版本比较、在 Langfuse 中查看逐题 Trace 与分数 |

两种方式都会以所选 Agent 的真实 RAG 链路回答；评测时关闭长期记忆和联网搜索，避免非知识库因素污染结果。Langfuse 实验不需要公网 Webhook 或端口穿透：后端通过 SDK 主动读取 Dataset、执行 RAG、再将 Experiment 和评分写回 Langfuse。

### 首次配置与日常运行

1. 在「系统设置 → 可观测性」保存 Langfuse Public Key、Secret Key，并点击测试连接。
2. 在「数据集管理」选择知识库，新增或导入黄金题。每道普通知识题应包含：问题、期望文档 ID、必备事实；可选填写参考答案。拒答/无答案题可以没有期望文档 ID。
3. 在 Agent 详情中挂载该知识库，并确认 Agent 与知识库均处于启用状态。
4. 运行本地评测时，选择 Agent、已挂载知识库和 K 值（5、10 或 20）。
5. 要运行 Langfuse 实验时，先在「数据集管理」将该知识库的启用黄金题同步到 Langfuse Dataset；然后选择同一 Agent、该 Agent 已挂载的知识库、Dataset 和 K 值，启动实验。
6. 管理台会逐题更新进度、Token 用量和本地评分；Langfuse 实验结束后可通过运行记录中的「查看实验」进入 Langfuse。

K 同时是 RAG 取回候选的数量，以及检索指标的计算范围。`Recall@K` 衡量期望文档是否在前 K 个候选中，`NDCG@K` 衡量相关文档在前 K 个候选中的排序质量。忠实度、问答相关性和问答准确性由 LLM Judge 在逐题回答后补写；因此检索指标通常会先出现，生成侧 Judge 分数稍后出现。

### 知识库迁移后的重建方案

迁移/导入知识库会生成新的知识库和文档记录；即使文件内容相同，新的文档 ID 也不能与迁移前的黄金集混用。按以下顺序恢复评测：

1. 导入知识库，等待文档解析和索引完成。
2. 将导入后的知识库重新挂载到目标 Agent。导入不会自动建立 Agent 与知识库的挂载关系。
3. 清理旧的问答缓存（管理台的清理缓存功能，或 `POST /api/v1/admin/clear-cache`），然后用管理台对话做一题带来源的验收，确认 Agent 确实检索到新知识库。
4. 在「数据集管理」针对**新知识库**重建黄金集：重新选择其当前文档 ID，校验必备事实和参考答案；不要直接沿用旧知识库 ID 或旧文档 ID。
5. 为迁移后的知识库同步一个新的 Langfuse Dataset（建议使用新的数据集名称），并在 Langfuse 实验中选择这个新 Dataset。
6. 先跑少量代表题验证来源、`Recall@K` 与 `NDCG@K`，再运行完整实验并记录实验名称，用于与迁移前版本比较。

> Dataset 题目的 `metadata.zhida_knowledge_base_id` 必须指向本次实验选择且已挂载到 Agent 的知识库。普通知识题若 `expected_document_ids` 为空，无法计算有意义的检索指标；拒答题为空则是合理的。同步使用带 Dataset 名称前缀的全局唯一 Item ID，避免不同 Dataset 之间发生 ID 冲突。

### 结果与故障边界

- Langfuse 实验每题都会固定上传忠实度、问答相关性、问答准确性、`Recall@K`、`NDCG@K`、输入 Token、命中缓存 Token、输出 Token 和缓存命中率。某题无法产生某项分数时会以 `0` 写入并附带原因，保证字段集合一致。
- 远端 Dataset 可以保留历史题目；若其关联的本地黄金题已删除，运行记录会安全地将该本地关联置空，而不会因外键错误中断实验。仍建议在数据集重构后同步并使用新 Dataset，避免旧题混入比较。
- 同一个 Agent 与同一份数据集同一时间只能运行一个评测。运行中可取消；取消会阻止后续题继续调用 RAG/模型，SDK 后台收尾不影响本地记录最终标记为已取消。
- Langfuse 实验会绕过问答缓存以获得真实的检索和生成结果；迁移验收时也应清缓存，避免旧缓存回答表现为“基于模型自身知识”。

### 网络检索（可选）

RAG 本地证据不足时自动补充联网搜索（支持 Tavily / Exa）：

```env
ZHIDA_WEB_SEARCH_ENABLED=true
ZHIDA_WEB_SEARCH_PROVIDER=tavily
ZHIDA_WEB_SEARCH_API_KEY=tvly-...
ZHIDA_WEB_SEARCH_MAX_RESULTS=3
```

---

## API 文档

完整的 API 文档参见 [API_DOCS.md](API_DOCS.md)。

核心端点：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/auth/captcha` | GET | 获取图形验证码 |
| `/api/v1/auth/admin/register` | POST | 首次部署注册管理员 |
| `/api/v1/auth/admin/login` | POST | 管理员登录 |
| `/api/v1/auth/user/login` | POST | 用户激活码登录 |
| `/api/v1/auth/admin/access-codes` | GET/POST | 激活码列表 / 创建 |
| `/api/v1/user/chat/stream` | POST | 用户端流式问答（SSE） |
| `/api/v1/knowledge/bases` | GET/POST | 知识库 CRUD |
| `/api/v1/knowledge/bases/{kb_id}/upload` | POST | 文档上传（含格式校验）|
| `/api/v1/knowledge/bases/{kb_id}/web/import` | POST | 网页导入 |
| `/api/v1/agents` | GET/POST | Agent CRUD |
| `/api/v1/agents/{id}/start` | POST | 启动 Agent |
| `/api/v1/qa/ask` | POST | 提问 |
| `/api/v1/admin/settings` | GET/PUT | 系统设置（含维护模式） |
| `/api/v1/admin/observability` | GET/PUT | Langfuse 可观测性配置 |
| `/api/v1/admin/observability/test` | POST | 测试已保存的 Langfuse 连接 |

---

## 作为服务接入其他应用

智答引擎可以作为一个独立的本地 RAG 服务，被 Web 应用、桌面端、企业内部工具或其他 AI Agent 调用。调用方只需要保存 `agent_id`；该 Agent 已挂载的所有知识库会一起参与检索。

> 以下管理 API（包括 `/qa/ask`）需要管理员会话。浏览器在管理台登录后会自动携带 Cookie；命令行或服务端接入请使用受保护的 Cookie Jar，或在反向代理前增加面向调用方的认证层。用户端应使用 `/api/v1/user/chat/stream`，不能把用户身份字段直接传给管理 API。

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
# 管理员登录一次，将会话保存到受保护的本地 Cookie Jar
curl -c ./zhida-admin.cookie \
  -X POST http://127.0.0.1:18900/api/v1/auth/admin/login \
  -H 'Content-Type: application/json' \
  -d '{"captcha_id":"...","captcha_answer":"...","username":"admin","password":"..."}'

# 创建 Agent（新建后默认停用）
curl -b ./zhida-admin.cookie -X POST http://127.0.0.1:18900/api/v1/agents \
  -H 'Content-Type: application/json' \
  -d '{"name":"产品知识助手","description":"回答产品与交付问题"}'

# 将已有知识库 12 挂载到 Agent 3
curl -b ./zhida-admin.cookie -X POST http://127.0.0.1:18900/api/v1/knowledge/bases/12/attach \
  -H 'Content-Type: application/json' \
  -d '{"agent_id":3}'

# 启动：启动后即可在管理台对话页和外部问答 API 中使用
curl -b ./zhida-admin.cookie -X POST http://127.0.0.1:18900/api/v1/agents/3/start
```

### 3. 调用 RAG 问答

`POST /api/v1/qa/ask` 是其他应用最常用的接口。它会执行混合检索、父块扩展、回答生成与来源整理，并返回本轮使用的模型和文档来源。

```bash
curl -b ./zhida-admin.cookie -X POST http://127.0.0.1:18900/api/v1/qa/ask \
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
  credentials: 'include', // 管理员已登录且为同站请求时才会携带 Cookie
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
curl -b ./zhida-admin.cookie -X POST http://127.0.0.1:18900/api/v1/knowledge/bases/12/upload \
  -F 'file=@./售后政策.pdf'
```

云文档导入可通过管理台完成。飞书导入会创建后台任务并在知识库详情页显示逐篇进度；同一正文基于 SHA-256 自动去重。

### 5. 接入边界

- 问答接口只接受已启用的 Agent；停止 Agent 后，调用会返回“Agent 不存在或未启用”。
- `/api/v1/qa/ask` 当前返回完整 JSON 回答；外部应用需要打字机效果时，应在自身 UI 层按段或按字展示 `answer`。
- 管理 API 使用管理员 Cookie，不是面向公网的多租户 API。接入第三方应用前，应由宿主应用或网关负责身份认证、授权和限流，且不要把管理员 Cookie 下发到客户端。
- API Key、飞书密钥等只在本机加密保存；接入方不应从 API 或日志中读取、传递这些密钥。

---

## 架构说明

完整的架构设计参见 [ARCHITECTURE.md](ARCHITECTURE.md)。

### 文档解析流程

```
上传文件 → magic bytes 校验 → 解析（MinerU / 本地）→ 质量检查 → 父子块切分 → 向量化 → ChromaDB
```

### 问答管线（RAG 增强）

```
问题 → 请求合并 → 缓存命中 → 记忆检索 → 问题改写（上下文模型生成最多 3 条改写）
    → 多路混合检索（加权 RRF 融合，父块粒度去重）
    → 联网补充（可选）→ Prompt 构建 → LLM 生成（主 → 降级 → 离线兜底）
    → 回写缓存 / 记忆 / Langfuse
```

检索排序由 RRF 融合（向量 0.45 / 关键词 0.55）+ 身份文件名加分完成。

### 上下文管理

每个 Agent 有独立上下文窗口（`context_window_k`，默认 64K）。系统按占用比例自动调整：

- **≥95%**：触发会话压缩，把早期对话滚动压缩为摘要（存于会话，游标防重复压缩）
- **≥80%**：只保留最近 4 轮原文，同时降低检索量与记忆量
- **≥60%**：保留最近 6 轮原文
- 其余：保留最近 12 轮

压缩与改写由「重写/压缩模型」执行（未单独配置时复用主模型），两任务各有独立超时。

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
