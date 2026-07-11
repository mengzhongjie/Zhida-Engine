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
│  │  │  渠道适配器   │  │  自动学习   │  │  格式校验   │      │    │
│  │  │ (QQ/微信)    │  │ (QA提取)    │  │ (magic字节) │      │    │
│  │  └─────────────┘  └─────────────┘  └─────────────┘      │    │
│  │                                                          │    │
│  │  ┌───────────────────────────┐  ┌─────────────┐          │    │
│  │  │ MinerU 可选解析           │  │  记忆服务   │          │    │
│  │  │ (embedded / HTTP 服务)   │  │  (Mem0)    │          │    │
│  │  └───────────────────────────┘  └─────────────┘          │    │
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
              │  MinerU API (可选 Docker 服务)   │
              └──────────────────────────────────┘
```

## 二、核心模块说明

### 1. 文档解析链路

**文档处理流程（上传前格式校验 → 解析 → 父子块切分 → 向量化）：**

```
文档上传 (multipart/form-data)
    │
    ▼
┌────────────────────────────────────────────┐
│  上传前预检 (UploadPreChecker)               │
│  ├─ FileFormatValidator: magic bytes 检测   │
│  │   真实类型 vs 扩展名对比 → 不匹配则拒绝    │
│  ├─ 文件名清洗 (移除路径穿越/危险字符)        │
│  ├─ 文件完整性检查 (PDF %%EOF, ZIP testzip) │
│  └─ 空文件 / 超大小检测                     │
└─────────────────────┬──────────────────────┘
                      │ 通过
                      ▼
┌────────────────────────────────────────────┐
│  DocumentParser.parse()                     │
│  ├─ MinerU 解析（可选，ENABLE_MINERU=true） │
│  │   ├─ embedded 模式: 直接 import magic_pdf│
│  │   └─ service 模式: HTTP 调用远程服务     │
│  ├─ 本地解析器（pdfplumber/python-docx/...）│
│  │   PDF → pdfplumber + 表格提取            │
│  │   DOCX → python-docx + 表格提取          │
│  │   XLSX → openpyxl + pandas → Markdown   │
│  │   TXT/MD/JSON/XML → 原生读取             │
│  │   CSV  → pandas → Markdown 表格          │
│  └─ 降级链：MinerU → 本地 → 纯文本 → 分页   │
└─────────────────────┬──────────────────────┘
                      │
                      ▼
┌────────────────────────────────────────────┐
│  解析结果质检 (ParseQualityChecker)          │
│  ├─ 空内容 / 乱码检测                        │
│  ├─ 文本完整度评分 (0-100)                   │
│  ├─ 语言检测 (langdetect)                    │
│  └─ 结构质量评分 (表格/公式/代码/标题)        │
└─────────────────────┬──────────────────────┘
                      │ 通过
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
    Embedder.embed()  ──  向量化（本地BGE模型 / 云端API）
            │
            ▼
    IndexManager.index_chunks()  ──► ChromaDB Collection
```

### 2. 渠道适配层（Channel Adapter）

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
    │     - 扫码登录 (需 NapCat 运行中)
    │     - 群聊/好友列表 (通过 NapCat API)
    │     - 群成员列表
    │     - 消息收发 (HTTP API)
    │
    └── WeChatAdapter (基于 Wechaty)
          - 扫码登录 (需 Wechaty Puppet Token)
          - 群聊/好友列表
          - 群成员列表
          - 消息收发 (WebSocket)

注意：渠道适配器不再提供模拟模式，SDK 未就绪时 API 返回明确的错误信息。
```

**关键方法：**
- `generate_qrcode()` - 生成登录二维码
- `check_login_status(login_id)` - 查询登录状态
- `get_contact_list()` - 获取群聊+好友列表
- `get_group_member_list(group_id)` - 获取群成员列表
- `start()` / `stop()` - 启动/停止监听
- `send(request)` - 发送消息

### 3. 向量化服务设计（代理模式）

```
embedding_service (全局单例，EmbeddingServiceProxy)
    │
    ├── switch_to(new_impl)  -- 运行时切换内部实现
    │
    ├── LocalBGEEmbedding (本地模型，sentence-transformers)
    │     model: BAAI/bge-large-zh-v1.5
    │     dimension: 1024
    │
    └── CloudEmbedding (云端 API，OpenAI 兼容)
          model: text-embedding-3-small 等
          dimension: 1536 等
```

### 4. QA 问答服务

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

### 5. 格式校验模块

```
validation/              (app/services/validation/)
  ├── config.py          → ValidationConfig (ZHIDA_FORMAT_*)
  ├── file_validator.py  → FileFormatValidator (magic bytes 检测)
  ├── precheck.py        → UploadPreChecker (上传前三合一)
  └── quality_checker.py → ParseQualityChecker (解析后多维评分)

上传前预检:
  magic bytes → 真实类型 (PDF %PDF, ZIP 容器, PNG 89PNG...)
    ├─ 扩展名匹配 → 通过 / 拒绝 (STRICT 模式)
    ├─ 文件名清洗 → 移除 ../ 等危险字符
    └─ 损坏检测   → PDF %%EOF, ZIP testzip, PNG IEND

解析后质检:
  ├─ 空内容检测 → FORMAT_MIN_TEXT_LENGTH (默认 10)
  ├─ 乱码检测   → 不可打印字符 / � / 控制字符比例
  ├─ 语言检测   → langdetect (中文/英文/混合)
  ├─ 完整度评分 → 结尾符号/页码/空白率/密度 (0-100)
  └─ 结构评分   → 表格/公式/代码/标题对应 (0-100)
```

### 6. MinerU 解析（可选）

```
MinerU 集成在 DocumentParser 内部，作为可选的前置解析策略。
需设置 ZHIDA_ENABLE_MINERU=true 并选择部署模式：

嵌入式模式 (embedded):
  - pip install magic-pdf (约 4-6GB, 含 torch + paddleocr)
  - 直接调用 Python API aio_do_parse()
  - 支持后端: pipeline(CPU可用) / vlm-engine(GPU)

HTTP 服务模式 (service):
  - Docker: docker run -d -p 18901:8000 opendatalab/mineru:latest
  - 通过 HTTP 调用 mineru-api 异步任务接口
  - 进程隔离，避免 AGPL-3.0 许可证传染性

MinerU 优势: 布局检测 / OCR / 公式 LaTeX / 表格结构识别
降级策略:   MinerU 失败 → 自动回退到本地解析器 (pdfplumber 等)
```

### 7. 缓存层

```
L1: 内存字典 (进程内，最快)
    │
    ▼
L2: diskcache (SQLite 持久化，跨进程)
    │
    ▼
L3: 实际 LLM/检索调用 (最慢)
```

## 三、数据模型

### 核心实体关系

```
Agent (1) ──┬── (N) KnowledgeBase (可独立存在，agent_id 可空)
            │     支持动态挂载/解绑
            │
            ├── (N) ChannelConfig
            │
            ├── (N) LLMConfig
            │
            └── (N) QAHistory

KnowledgeBase (1) ── (N) Document ── (N) DocumentChunk (父块)
        │                                   │
        │                                   ├── ChromaDB 子块向量
        │                                   │   (通过 parent_id 关联)
        │                                   │
        │                                   └── metadata_json (TextChunk 元数据)
        │
        └── 统计字段：document_count, chunk_count, parent_chunk_count, total_size_bytes

Document
    - status: pending / processing / completed / failed
    - chunk_count: 子切片数量
    - parent_chunk_count: 父块数量
    - parse_time_ms: 解析耗时
    - 注：解析成功即为 completed，向量化索引失败不影响状态（在 error_message 中提示）

EmbeddingConfig (id=1 单例)
    - mode: local / cloud
    - local_model, local_device
    - cloud_base_url, cloud_api_key (加密), cloud_model, cloud_dimension

ChannelConfig
    - channel_type: qq / wechat
    - chat_id: 群聊/用户 ID
    - target_users: 监听用户白名单（JSON 数组）
    - listen_mode: all / mentioned / questions
```

## 四、扫码登录流程

```
前端                          后端                          渠道 SDK
 │                              │                              │
 │  1. 点击"添加渠道"            │                              │
 │─────────────────────────────►│                              │
 │                              │                              │
 │  2. 显示扫码弹窗              │                              │
 │  3. 选择 QQ/微信 平台          │                              │
 │                              │                              │
 │  4. 请求生成二维码            │                              │
 │─────────────────────────────►│                              │
 │                              │  5. 调用渠道 SDK 生成二维码   │
 │                              │─────────────────────────────►│
 │                              │                              │
 │                              │  6. 返回二维码内容 + login_id │
 │                              │◄─────────────────────────────│
 │  7. 显示二维码                │                              │
 │◄─────────────────────────────│                              │
 │                              │                              │
 │  8. 轮询登录状态 (2s/次)      │                              │
 │─────────────────────────────►│                              │
 │                              │  9. 查询 SDK 登录状态         │
 │                              │─────────────────────────────►│
 │                              │                              │
 │  状态: waiting/scanned/...   │                              │
 │                              │                              │
 │  10. 登录成功 (status=success)│                              │
 │◄─────────────────────────────│                              │
 │                              │                              │
 │  11. 显示群聊/好友列表         │                              │
 │─────────────────────────────►│                              │
 │                              │                              │
 │  12. 选择群聊/好友             │                              │
 │  13. (群聊) 查看群成员         │                              │
 │  14. 选择监听用户 (可选)       │                              │
 │  15. 确认添加渠道             │                              │
 │─────────────────────────────►│                              │
 │                              │  16. 保存到 ChannelConfig 表 │
 │  17. 添加成功                 │                              │
 │◄─────────────────────────────│                              │
```
