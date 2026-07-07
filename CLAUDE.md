# CLAUDE.md

本文件为 Claude Code（claude.ai/code）提供此仓库的代码操作指引。

## 项目概览

智答引擎（ZhiDa Engine）—— 基于 RAG 架构的个人 AI 知识助手。Windows 桌面应用，接入微信群/QQ 群，支持从聊天记录中持续自动学习知识。

### 技术栈

- **后端框架**: Python 3.11+ / FastAPI / SQLAlchemy (async) / SQLite
- **向量数据库**: ChromaDB（嵌入式）
- **嵌入模型**: sentence-transformers（BAAI/bge-large-zh-v1.5）
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
│   │   └── database.py          # SQLAlchemy 异步引擎 + 会话工厂
│   ├── models/                  # SQLAlchemy ORM 模型
│   │   ├── agent.py             # Agent 实例（核心实体）
│   │   ├── knowledge.py         # KnowledgeBase + Document
│   │   ├── qa.py                # QAHistory + QAPair
│   │   ├── channel.py           # ChannelConfig
│   │   └── llm_config.py        # LLMConfig + ProviderConfig
│   ├── schemas/
│   │   └── llm_config.py        # Pydantic Schema（LLM 配置 API）
│   ├── api/v1/
│   │   ├── config/router.py     # 唯一已实现的 API：LLM 厂商/配置 CRUD + 测试连接
│   │   ├── knowledge/           # 空文件夹，待实现
│   │   ├── qa/                  # 空文件夹，待实现
│   │   └── channel/             # 空文件夹，待实现
│   └── services/
│       ├── qa/                  # HybridRetriever, Reranker, AnswerGenerator, PromptTemplate
│       ├── knowledge/           # DocumentParser, TextSplitter, Embedder, IndexManager
│       ├── llm/                 # LLMGateway, ProviderTemplate（8 个内置 + 自定义）
│       ├── learning/            # QAExtractor, MessageListener, LearningScheduler
│       ├── channel/             # ChannelAdapter 基类 + WeChat + QQ 适配器
│       └── cache/               # QueryCache, SingleFlight, DegradationManager, RateLimiter
├── bots/                        # 空文件夹，预留机器人启动脚本
└── tests/                       # 仅含空 __init__.py，尚未编写测试
```

## 架构说明

### RAG 流水线

1. **文档 → 知识库**: `DocumentParser.parse()` → `TextSplitter.split_adaptive()` → `IndexManager.index_chunks()` → ChromaDB
2. **问题 → 回答**: `HybridRetriever.retrieve()` → `Reranker.rerank()` → `AnswerGenerator.generate()` → `LLMGateway.chat()`

### Agent 中心模型

`Agent` 是核心实体。每个 Agent 拥有独立的：
- 知识库（上传文档 + 聊天提取的问答对）
- LLM 配置（主模型 + 降级模型）
- 渠道配置（监听的微信群/QQ 群）
- 学习策略

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
- **API 层部分实现**：只有 `/api/v1/llm/` 的 LLM 配置 CRUD 有路由；知识库、问答、渠道 API 均为空桩
- **尚未编写测试**（`backend/tests/__init__.py` 为空）
- **尚无前端代码**（`frontend-admin/` 为空）
- **尚无机器人启动脚本**（`bots/qq_bot/` 和 `bots/wechat_bot/` 为空）
- Git 历史包含 5 个按顺序构建 Service 层的功能提交

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
- `query_cache`（services/cache/query_cache.py）
- `single_flight`（services/cache/idempotency.py）
- `degradation_manager`（services/cache/degradation.py）
- `rate_limiter`（services/cache/rate_limiter.py）
- `adapter_factory`（services/channel/base.py）
- `settings`（core/config.py）
