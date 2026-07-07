# 智答引擎（ZhiDa Engine）架构图

## 一、整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        前端管理台 (React)                        │
│  ┌──────────┬──────────┬──────────┬──────────┬──────────┐       │
│  │  仪表盘   │ 知识库   │ Agent   │ 渠道配置 │ 系统设置  │       │
│  └──────────┴──────────┴──────────┴──────────┴──────────┘       │
└────────────────────────────────┬────────────────────────────────┘
                                 │ HTTP REST API
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                      FastAPI 后端服务                            │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                    API 层 (api/v1/)                      │    │
│  │  config/  embedding/  knowledge/  agent/  channel/      │    │
│  │  qa/  admin/                                            │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                  │
│                              ▼                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                   Service 服务层                          │    │
│  │                                                          │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐      │    │
│  │  │  LLM 网关    │  │  知识库服务   │  │  QA 问答     │      │    │
│  │  │ (litellm)   │  │  (解析/切分) │  │ (检索/生成) │      │    │
│  │  └─────────────┘  └─────────────┘  └─────────────┘      │    │
│  │                                                          │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐      │    │
│  │  │  渠道适配器   │  │  自动学习   │  │  记忆服务   │      │    │
│  │  │ (QQ/微信)    │  │ (QA提取)    │  │  (Mem0)    │      │    │
│  │  └─────────────┘  └─────────────┘  └─────────────┘      │    │
│  │                                                          │    │
│  │  ┌───────────────────────────────────────────────┐      │    │
│  │  │            缓存服务 (diskcache)                 │      │    │
│  │  │  查询缓存 / 单飞合并 / 降级策略 / 限流          │      │    │
│  │  └───────────────────────────────────────────────┘      │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                  │
│                              ▼                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                    数据存储层                              │    │
│  │                                                          │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │    │
│  │  │   SQLite     │  │  ChromaDB    │  │  diskcache   │   │    │
│  │  │ (业务数据)   │  │  (向量索引)  │  │   (缓存)     │   │    │
│  │  └──────────────┘  └──────────────┘  └──────────────┘   │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
              ┌──────────────────────────────────┐
              │       外部渠道 / 模型服务         │
              │  QQ (NapCat) / 微信 (Wechaty)    │
              │  LLM API / Embedding API         │
              └──────────────────────────────────┘
```

## 二、核心模块说明

### 1. 渠道适配层（Channel Adapter）

```
ChannelAdapterFactory (全局单例，adapter_factory)
    │
    ├── register(type, class)  -- 注册适配器类
    ├── create(type)           -- 获取适配器实例（单例模式）
    └── get_supported_channels()
           │
           ▼
ChannelAdapter (抽象基类)
    │
    ├── QQAdapter (基于 NapCat QQ)
    │     - 扫码登录（支持模拟模式）
    │     - 群聊/好友列表
    │     - 群成员列表
    │     - 消息收发
    │
    └── WeChatAdapter (基于 Wechaty)
          - 扫码登录（支持模拟模式）
          - 群聊/好友列表
          - 群成员列表
          - 消息收发

模拟模式（Mock Mode）：
  - 当 NapCat / Wechaty 未配置或不可用时，自动进入模拟模式
  - 扫码登录：状态自动推进 waiting → scanned → confirmed → success（约6次轮询）
  - 联系人列表：返回预设的模拟数据
  - 用于演示和前端开发调试
```

**关键方法：**
- `generate_qrcode()` - 生成登录二维码
- `check_login_status(login_id)` - 查询登录状态
- `get_contact_list()` - 获取群聊+好友列表
- `get_group_member_list(group_id)` - 获取群成员列表
- `get_group_members(chat_id)` - 获取群成员（简化版）
- `start(message_handler)` - 启动监听
- `stop()` - 停止监听
- `send(request)` - 发送消息

### 2. 知识库服务（Knowledge Service）

**文档处理流程（父子块切分 - Small-to-Big）：**

```
文档上传
    │
    ▼
DocumentParser.parse()  ──  解析文档（PDF/Word/Excel/TXT/MD等）
    │
    ▼
TextSplitter.split_parent_child()  ──  父子块切分（LangChain）
    │                                 父块: 800字符（存入SQLite）
    │                                 子块: 200字符，重叠50（存入ChromaDB）
    │
    ├── DocumentChunk (父块) ──► SQLite (document_chunks表)
    │
    └── TextChunk (子块)
            │
            ▼
    Embedder.embed()  ──  向量化（本地/云端）
            │
            ▼
    IndexManager.index_chunks()  ──► ChromaDB Collection
```

**向量化服务设计（代理模式）：**

```
embedding_service (全局单例，EmbeddingServiceProxy)
    │
    ├── switch_to(new_impl)  -- 运行时切换内部实现
    │
    ├── LocalBGEEmbedding (本地模型，sentence-transformers)
    │     model: BAAI/bge-large-zh-v1.5
    │     dimension: 1024
    │
    └── CloudEmbedding (云端 API，OpenAI兼容)
          model: text-embedding-3-small 等
          dimension: 1536 等

为什么用代理模式？
  Python 中 from x import y 的导入机制，当 y 被重新赋值时，
  已导入的模块不会自动更新。使用 Proxy 模式后，所有模块
  共享同一个 Proxy 对象，切换内部 _impl 后全局生效。

初始化流程：
  应用启动 → init_embedding_config(db) 从数据库加载配置
    → 数据库有配置 → 更新 settings → create_embedding_service()
    → 数据库无配置 → 使用默认值 → 保存到数据库
  运行时更新 → PUT /embedding/config → 保存到数据库 → _reload_embedding_service()
    → embedding_service.switch_to(new_impl) → 全局生效

错误处理：
  CloudEmbedding._format_error() 统一格式化错误
    401 → API Key 无效或已过期
    404 → API 地址不存在（检查 Base URL）
    429 → 请求过于频繁
    5xx → 服务器错误
    连接错误 → 检查网络和 Base URL
```

### 3. QA 问答服务

```
用户问题
    │
    ▼
HybridRetriever.retrieve()  ──  混合检索（向量+关键词）
    │                            子块检索 → 通过parent_id获取父块
    ▼
Reranker.rerank()  ──  重排序（可选）
    │
    ▼
AnswerGenerator.generate()  ──  答案生成
    │
    ▼
LLMGateway.chat()  ──  LLM调用（主模型/降级模型）
```

### 4. 记忆层（Mem0）

```
对话消息
    │
    ▼
MemoryService.add()  ──  自动提取记忆（偏好/事实/关系）
    │
    ▼
ChromaDB (记忆向量) + SQLite (元数据)

检索时:
  用户问题
      │
      ▼
  MemoryService.search()  ──  语义检索相关记忆
      │
      ▼
  注入回答上下文
```

### 5. 缓存层

```
L1: 内存字典 (进程内，最快)
    │
    ▼
L2: diskcache (SQLite持久化，跨进程)
    │
    ▼
L3: 实际LLM/检索调用 (最慢)
```

## 三、数据模型

### 核心实体关系

```
Agent (1) ──┬── (N) KnowledgeBase (可独立存在，agent_id可空)
            │     支持动态挂载/解绑：POST /bases/{id}/attach, /bases/{id}/detach
            │
            ├── (N) ChannelConfig
            │
            ├── (N) LLMConfig
            │
            └── (N) QAHistory

KnowledgeBase (1) ── (N) Document ── (N) DocumentChunk (父块)
        │                                   │
        │                                   └── (N) ChromaDB 子块
        │                                       (通过 parent_id 关联)
        │
        └── 统计字段：document_count, chunk_count, parent_chunk_count, total_size_bytes

Document
    - status: pending / processing / completed / error
    - chunk_count: 子切片数量
    - parent_chunk_count: 父块数量
    - 注：解析成功即为 completed，向量化索引失败不影响状态（在 error_message 中提示）

EmbeddingConfig (id=1 单例)
    - mode: local / cloud
    - local_model, local_device
    - cloud_base_url, cloud_api_key (加密), cloud_model, cloud_dimension
    - 持久化到数据库，应用启动时自动加载

ChannelConfig
    - channel_type: qq / wechat
    - chat_id: 群聊/用户ID
    - target_users: 监听用户白名单（JSON数组）
    - listen_mode: all / mentioned / questions
```

## 四、扫码登录流程

```
前端                          后端                          渠道SDK
 │                              │                              │
 │  1. 点击"添加渠道"            │                              │
 │─────────────────────────────►│                              │
 │                              │                              │
 │  2. 显示扫码弹窗              │                              │
 │  3. 选择QQ/微信平台           │                              │
 │                              │                              │
 │  4. 请求生成二维码            │                              │
 │─────────────────────────────►│                              │
 │                              │  5. 调用渠道SDK生成二维码     │
 │                              │─────────────────────────────►│
 │                              │                              │
 │                              │  6. 返回二维码内容+login_id  │
 │                              │◄─────────────────────────────│
 │  7. 显示二维码                │                              │
 │◄─────────────────────────────│                              │
 │                              │                              │
 │  8. 轮询登录状态 (2s/次)      │                              │
 │─────────────────────────────►│                              │
 │                              │  9. 查询SDK登录状态          │
 │                              │─────────────────────────────►│
 │                              │                              │
 │  状态: waiting/scanned/...   │                              │
 │                              │                              │
 │  10. 登录成功 (status=success)│                              │
 │◄─────────────────────────────│                              │
 │                              │                              │
 │  11. 显示群聊/好友列表        │                              │
 │─────────────────────────────►│                              │
 │                              │  12. 获取联系人列表          │
 │                              │─────────────────────────────►│
 │                              │                              │
 │  13. 选择群聊/好友            │                              │
 │                              │                              │
 │  14. (群聊)查看群成员         │                              │
 │─────────────────────────────►│                              │
 │                              │  15. 获取群成员列表          │
 │                              │─────────────────────────────►│
 │                              │                              │
 │  16. 选择监听用户(可选)       │                              │
 │                              │                              │
 │  17. 确认添加渠道             │                              │
 │─────────────────────────────►│                              │
 │                              │  18. 保存到ChannelConfig表   │
 │                              │                              │
 │  19. 添加成功                 │                              │
 │◄─────────────────────────────│                              │
```
