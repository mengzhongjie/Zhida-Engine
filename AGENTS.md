# AGENTS.md

本文件为 Codex（Codex.ai/code）提供此仓库的代码操作指引。

## 项目概览

智答引擎（ZhiDa Engine）—— 基于 RAG 架构的个人 AI 知识助手。Windows 桌面应用，接入微信群/QQ 群，支持从聊天记录中持续自动学习知识。

### 技术栈

- **后端框架**: Python 3.11+ / FastAPI / SQLAlchemy (async) / SQLite
- **向量数据库**: ChromaDB（嵌入式）
- **嵌入模型**: sentence-transformers（BAAI/bge-large-zh-v1.5）+ 云端 API（OpenAI 兼容，7 个内置厂商模板）
- **LLM 网关**: litellm + OpenAI 兼容客户端（8 个内置厂商模板 + 自定义）
- **缓存**: diskcache（基于 SQLite，无需 Redis）
- **文档解析**: pdfplumber, python-docx, openpyxl, pandas
- **中文分词**: jieba

## 开发环境配置

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 启动服务

```bash
cd backend && python main.py
```

服务启动在 `http://127.0.0.1:18900`，API 文档在 `http://127.0.0.1:18900/api/docs`（仅 debug 模式）。

### 运行单个模块或测试

```bash
# 运行单个 Python 模块
cd backend && python -m app.services.knowledge.parser

# 运行测试
cd backend && python -m pytest -xvs
```

### 健康检查

```bash
curl http://127.0.0.1:18900/health
```

## 项目结构

```
backend/
├── main.py                      # 应用入口：FastAPI 初始化、CORS、路由注册
├── requirements.txt
├── app/
│   ├── core/
│   │   ├── config.py            # Pydantic Settings（环境变量 + .env + 默认值）
│   │   ├── database.py          # SQLAlchemy 异步引擎 + 会话工厂
│   │   ├── security.py          # 加密解密、进程锁、沙箱
│   │   ├── sandbox.py           # 沙箱管理器
│   │   └── resource_manager.py  # 资源管理器
│   ├── models/                  # SQLAlchemy ORM 模型
│   │   ├── agent.py             # Agent 实例（核心实体）
│   │   ├── knowledge.py         # KnowledgeBase（agent_id 可空） + Document + DocumentChunk（父块）
│   │   ├── qa.py                # QAHistory + QAPair
│   │   ├── channel.py           # ChannelConfig
│   │   └── llm_config.py        # LLMConfig + ProviderConfig
│   ├── schemas/                 # Pydantic Schema
│   │   ├── llm_config.py        # LLM 配置 API
│   │   ├── embedding.py         # 向量化配置 API
│   │   ├── knowledge.py         # 知识库 API
│   │   ├── agent.py             # Agent API
│   │   ├── channel.py           # 渠道 API
│   │   ├── admin.py             # 系统管理 API
│   │   └── qa.py                # 问答 API
│   ├── api/v1/
│   │   ├── config/router.py     # LLM 厂商/配置 CRUD + 测试连接 + 使用统计
│   │   ├── embedding/router.py  # 向量化配置 CRUD + 测试连接 + 厂商模板
│   │   ├── knowledge/router.py  # 知识库 CRUD + 文档上传/删除 + 统计
│   │   ├── admin/router.py      # 模块开关 + 系统设置
│   │   ├── agent/router.py      # Agent CRUD + 启动/停止
│   │   ├── channel/router.py    # 渠道 CRUD + 监听控制
│   │   └── qa/router.py         # 问答 + 历史
│   └── services/
│       ├── qa/                  # HybridRetriever, Reranker, AnswerGenerator, PromptTemplate
│       ├── knowledge/           # DocumentParser, TextSplitter, Embedder, IndexManager, EmbeddingProviders
│       ├── llm/                 # LLMGateway, ProviderTemplate（8 个内置 + 自定义）
│       ├── learning/            # QAExtractor, MessageListener, LearningScheduler
│       ├── channel/             # ChannelAdapter 基类 + WeChat + QQ 适配器
│       ├── memory/              # MemoryService（基于 Mem0 的长期记忆层）
│       └── cache/               # QueryCache, SingleFlight, DegradationManager, RateLimiter
├── bots/                        # 空文件夹，预留机器人启动脚本
└── tests/                       # 测试用例
```

## 架构说明

### RAG 流水线

1. **文档 → 知识库（父子块切分 / Small-to-Big）**:
   - `DocumentParser.parse()` → `TextSplitter.split_parent_child()`
   - 基于 **LangChain RecursiveCharacterTextSplitter** 实现
   - 父块（800 字符）→ 存入 `document_chunks` 表（SQLite）
   - 子块（200 字符，重叠 50）→ `Embedder.embed()` → `IndexManager.index_chunks()` → ChromaDB
   - 代码块保护：切分前用占位符替换代码块，切分后恢复，确保代码完整性
2. **问题 → 回答**: `HybridRetriever.retrieve()`（子块检索 → 父块扩展）→ `Reranker.rerank()` → `AnswerGenerator.generate()` → `LLMGateway.chat()`

### Agent 中心模型

`Agent` 是核心实体。每个 Agent 拥有独立的：
- 知识库（可挂载多个独立知识库，支持先创建知识库再挂载）
- LLM 配置（主模型 + 降级模型）
- 渠道配置（监听的微信群/QQ 群）
- 学习策略

### 知识库模型

知识库支持独立创建和管理，不归属任何 Agent（`agent_id = NULL`）。
创建 Agent 时可选择挂载已有的独立知识库，也可在 Agent 详情页动态挂载/解绑。
每个知识库包含独立的文档集合、向量化索引和统计信息。

### 向量化模式

支持两种向量化模式，可在设置页面切换：
- **本地模式**：使用 sentence-transformers 加载本地模型（如 BAAI/bge-large-zh-v1.5）
- **云端模式**：使用 OpenAI 兼容 API，内置 7 个主流厂商模板（OpenAI、阿里云百炼、智谱、月之暗面、字节豆包、DeepSeek、硅基流动）

### 记忆层（Mem0）

基于 Mem0 的长期记忆层，为 AI 提供跨会话的个性化记忆能力：

- **自动提取**：从对话中自动提取用户偏好、事实、关系
- **语义检索**：通过向量相似度检索相关记忆，注入到回答上下文
- **自动维护**：自动更新、合并、删除矛盾记忆
- **多级隔离**：支持 user_id / agent_id / run_id 三级隔离
- **本地部署**：使用 ChromaDB + sentence-transformers，数据完全本地存储

核心文件：`app/services/memory/memory_service.py`（全局单例 `memory_service`）

### 模块开关（config.py）

所有重功能均有开关控制：`ENABLE_SINGLE_FLIGHT`、`ENABLE_GRAPH_RETRIEVAL`、`ENABLE_RERANK`、`ENABLE_STREAMING`、`ENABLE_AUTO_LEARNING`、`ENABLE_SOURCE_CITATION`、`ENABLE_AUTO_MENTION`。

### 渠道适配器模式

`ChannelAdapter`（抽象基类）→ `WeChatAdapter` / `QQAdapter`。新增渠道只需实现 `_do_start()`、`_do_stop()`、`_do_send()`、`_parse_message()`，然后通过 `adapter_factory.register(type, class)` 注册。

### 缓存层级

- **L1**: 内存字典（最快，进程内）
- **L2**: diskcache（持久化，基于 SQLite）
- **L3**: 实际 LLM 调用（最慢）

### 降级策略

每个服务都有兜底方案：LLM 不可用 → 降级模型 → 离线提示语；检索失败 → 纯关键词 → 纯 LLM 回复；文档解析失败 → 纯文本提取 → 分页解析 → 跳过。

## 当前状态

- **Service 层已全部完成**：所有服务定义了全局单例实例
- **API 层大部分已实现**：
  - ✅ LLM 配置 CRUD + 测试连接 + 使用统计
  - ✅ 向量化配置 CRUD + 测试连接 + 厂商模板
  - ✅ 知识库 CRUD + 文档上传/删除 + 统计
  - ✅ 模块开关 + 系统设置
  - ✅ Agent CRUD + 启动/停止
  - ✅ 渠道管理 API
  - ⏳ 问答 API
- **前端管理台已实现**：
  - ✅ 仪表盘概览
  - ✅ 知识库管理（多知识库切换、文档上传、列表）
  - ✅ Agent 创建（3 步向导）+ 详情页（6 个 Tab）
  - ✅ 系统设置（4 个 Tab：LLM 配置、向量化配置、功能开关、系统信息）
- **已有测试用例**（`backend/tests/test_core.py`）
- **尚无机器人启动脚本**（`bots/qq_bot/` 和 `bots/wechat_bot/` 为空）

## 全局单例实例

这些实例在整个代码库中使用（在各 service 文件底部定义）：

- `llm_gateway`（services/llm/gateway.py）—— 切换 Agent 时需重新 `initialize(agent_id)`
- `hybrid_retriever`（services/qa/retriever.py）
- `reranker`（services/qa/reranker.py）
- `answer_generator`（services/qa/generator.py）
- `prompt_template`（services/qa/prompt.py）
- `document_parser`（services/knowledge/parser.py）
- `text_splitter`（services/knowledge/splitter.py）
- `embedding_service`（services/knowledge/embedder.py）
- `index_manager`（services/knowledge/indexer.py）
- `qa_extractor`（services/learning/qa_extractor.py）
- `listener_manager`（services/learning/live_listener.py）
- `learning_scheduler`（services/learning/scheduler.py）
- `memory_service`（services/memory/memory_service.py）—— Mem0 记忆层
- `query_cache`（services/cache/query_cache.py）
- `single_flight`（services/cache/idempotency.py）
- `degradation_manager`（services/cache/degradation.py）
- `rate_limiter`（services/cache/rate_limiter.py）
- `adapter_factory`（services/channel/base.py）
- `settings`（core/config.py）
