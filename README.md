# 智答引擎（ZhiDa Engine）

> 基于 RAG 架构的个人 AI 知识助手。Windows 桌面应用，接入微信群/QQ 群，支持从聊天记录中持续自动学习知识。

---

## 目录

- [功能特性](#功能特性)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [项目结构](#项目结构)
- [配置说明](#配置说明)
- [API 文档](#api-文档)
- [架构说明](#架构说明)

---

## 功能特性

- **📚 知识库管理** — 上传 PDF/DOCX/Excel/MD/TXT/CSV/JSON 等文档，自动解析、切分、向量化
- **🔍 RAG 问答** — 基于混合检索（向量 + 关键词）的智能问答，支持来源引用
- **🤖 Agent 管理** — 创建 AI 助手，绑定知识库和 LLM 配置
- **💬 渠道接入** — 支持 QQ（NapCat）和微信（Wechaty）群聊/私聊消息监听
- **♻️ 自动学习** — 从聊天记录中自动提取问答对，持续丰富知识库
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
| 嵌入模型 | sentence-transformers（BAAI/bge-large-zh-v1.5）+ 云端 API |
| LLM 网关 | litellm + OpenAI 兼容客户端（8 个内置厂商模板） |
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
| 部署 | 构建产物嵌入 FastAPI 静态文件服务 |

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
```

前端开发服务器在 `http://localhost:5173`，API 请求自动代理到后端 18900 端口。

### 生产构建

```bash
cd frontend-admin
npm run build
# 构建产物输出到 backend/static/，由 FastAPI 直接 serve
```

### Docker 部署

```bash
docker compose up -d
```

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
│   │       ├── channel/            # 渠道适配
│   │       ├── llm/                # LLM 网关
│   │       ├── qa/                 # 问答服务
│   │       ├── learning/           # 自动学习
│   │       ├── memory/             # Mem0 记忆层
│   │       └── cache/              # 缓存服务
│   └── tests/
├── frontend-admin/                 # React 管理后台
├── miniprogram/                    # 微信小程序
├── bots/                           # 机器人启动脚本（空）
├── cloudfunctions/                 # CloudBase 云函数
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
ENABLE_GRAPH_RETRIEVAL    # 图检索增强
ENABLE_RERANK             # 重排序
ENABLE_STREAMING          # 流式输出
ENABLE_AUTO_LEARNING      # 自动学习
ENABLE_SOURCE_CITATION    # 来源引用
```

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
| `/api/v1/admin/modules` | GET | 模块开关 |

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
