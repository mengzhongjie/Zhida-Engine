# 智答引擎（ZhiDa Engine）架构图

> 当前交付范围为**管理后台 + 独立用户站**。渠道（QQ/微信/NapCat/Wechaty）、群聊自动学习、独立重排序器为历史设计，当前版本未注册任何渠道/自动学习路由，检索排序由 RRF 融合完成；以 `README.md` 与 `API_DOCS.md` 为准。

## 一、整体架构

```
┌────────────────────────────────────────────────────────────────────────┐
│                          前端（React + Ant Design）                      │
│  ┌───────────────────────────┐  ┌───────────────────────────┐          │
│  │  管理台 admin.example.com │  │  用户站 app.example.com    │          │
│  │  仪表盘/知识库/Agent/      │  │  对话界面（独立前端，       │          │
│  │  LLM 配置/系统设置/激活码  │  │  仅含聊天功能）             │          │
│  └──────────────┬────────────┘  └──────────────┬────────────┘          │
│                 │                             │                        │
│                 └─────────── HTTP REST API ────┘                        │
└────────────────────────────────┬───────────────────────────────────────┘
                                 │ /api/v1
                                 ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      FastAPI 后端服务 (127.0.0.1:18900)                 │
│                                                                        │
│  ┌──────────────────────────── API 层 (api/v1/) ───────────────────┐   │
│  │  auth(认证)  user(用户站)  config(LLM)  embedding  vision        │   │
│  │  knowledge  agent  qa  admin                                    │   │
│  └──────────────────────────────┬──────────────────────────────────┘   │
│                                 │                                      │
│                                 ▼                                      │
│  ┌──────────────────────────── Service 服务层 ─────────────────────┐   │
│  │  ┌──────────────────────┐  ┌───────────────────────────────┐   │   │
│  │  │ LLM 网关              │  │ QA 问答管线                    │   │   │
│  │  │ 主模型/降级/上下文角色  │  │ 问题改写→多路检索→压缩→生成      │   │   │
│  │  └──────────────────────┘  └───────────────────────────────┘   │   │
│  │  ┌──────────────────────┐  ┌───────────────────────────────┐   │   │
│  │  │ 知识库服务             │  │ 上下文管理                     │   │   │
│  │  │ 解析/质检/切分/向量化   │  │ 会话压缩/窗口裁剪/摘要游标       │   │   │
│  │  └──────────────────────┘  └───────────────────────────────┘   │   │
│  │  ┌──────────────────────┐  ┌───────────────────────────────┐   │   │
│  │  │ 记忆服务 (Mem0)       │  │ 缓存服务 (diskcache)           │   │   │
│  │  │ 跨会话个性化记忆        │  │ 查询缓存/请求合并/降级/限流      │   │   │
│  │  └──────────────────────┘  └───────────────────────────────┘   │   │
│  │  ┌──────────────────────┐  ┌───────────────────────────────┐   │   │
│  │  │ 可观测性 (Langfuse)   │  │ 维护模式 / 额度 / 会话认证       │   │   │
│  │  └──────────────────────┘  └───────────────────────────────┘   │   │
│  └──────────────────────────────┬──────────────────────────────────┘   │
│                                 │                                      │
│                                 ▼                                      │
│  ┌──────────────────────────── 数据存储层 ──────────────────────────┐  │
│  │  SQLite (业务/会话/摘要)  ChromaDB (向量)  diskcache (缓存)       │  │
│  └───────────────────────────────────────────────────────────────┘  │
└────────────────────────────────┬──────────────────────────────────────┘
                                 │
                                 ▼
             ┌──────────────────────────────────────────────┐
             │           外部服务                            │
             │  LLM API（主/降级/上下文模型）                 │
             │  Embedding API（OpenAI 兼容云端）              │
             │  Langfuse 云端可观测性                         │
             │  Tavily/Exa 网络检索（可选）                   │
             │  MinerU API（可选 Docker 服务）                │
             │  飞书开放平台（可选数据源）                     │
             └──────────────────────────────────────────────┘
```

## 二、核心模块说明

### 1. 文档解析链路

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
│  │   TXT/MD/CSV/JSON/XML → 原生读取         │
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
    Embedder.embed()  ──  向量化（云端 API / 本地 BGE）
            │
            ▼
    IndexManager.index_chunks()  ──► ChromaDB Collection
```

其他导入路径：**网页导入**（后台抓取 → LLM 保真重写 → 视觉识别）、**飞书导入**（异步任务，逐篇进度 + SHA-256 去重）。文档处理支持取消（`cancel`），失败可重试与清除残留。

### 2. QA 问答管线（当前真实链路）

```
用户问题
    │
    ▼
qa_request_coalescer ── 进程内请求合并（同 Agent/用户/问题合并并发请求）
    │
    ▼
query_cache 命中检查 ── 命中直接返回缓存
    │ 未命中
    ▼
memory_service 记忆检索（可选，按上下文压力缩放条数）
    │
    ▼
_query_variants 问题改写 ── 保留原问题(权重1.3) + 上下文模型生成最多3条
    │                       改写查询(权重1.0)，仅用于检索
    ▼
HybridRetriever.retrieve_multi_query ── 并行多路检索，加权 RRF 融合
    │  每路: 子块向量检索 → 父块扩展 → 关键词检索 → RRF(向量0.45/关键词0.55)
    │        → 文件名精确匹配加分 → 父块粒度去重
    ▼
联网补充（可选）── 本地证据不足时调用 web_search_service (Tavily/Exa)
    │
    ▼
prompt_template.build_qa_prompt ── 上下文 + 记忆 + 会话摘要 + persona
    │
    ▼
LLMGateway.chat / chat_stream ── 主模型 → 降级 → 离线兜底
    │
    ▼
回写：非降级时写 query_cache；异步写记忆；异步上报 Langfuse
```

> **说明**：检索后的排序由 **RRF 融合 + 身份文件名加分** 完成，当前没有独立的 cross-encoder 重排器。流式生成有长度预算重试（最多提升到 12000 token）；并发由 `QAStreamConcurrency`（信号量 + 队列）+ `PerUserStreamGuard`（每用户单条）保护。

### 3. 上下文管理（Context Management）

```
Agent.context_window_k（默认 64K，范围 32-256）—— 每个 Agent 独立的上下文窗口
    │
    ▼
_context_usage_ratio ── 估算请求占用比例
    │  = (estimate_tokens(摘要+历史+问题) + 8000预留RAG/规则 + 12000输出预留)
    │    / (context_window_k × 1000)
    ▼
_context_policy（固定阈值策略）
    ├─ 占用率 ≥0.95 且历史>4轮 ──► 触发会话压缩 compact_conversation
    │     上下文模型生成滚动摘要 → 存 Conversation.context_summary
    │     推进 summarized_through_history_id 游标（防重复压缩）
    ├─ 占用率 ≥0.80 ──► 保留最近 4 轮原文
    ├─ 占用率 ≥0.60 ──► 保留最近 6 轮原文
    └─ 其余       ──► 保留最近 12 轮原文
    │
    ▼
_trim_records_to_budget ── 压缩后把请求压回窗口 55% 的安全水位
    │
    ▼
context_pressure 传入生成器，缩放检索与记忆：
    占用 ≥0.80 → top_k 压到 4、记忆 1 条
    占用 ≥0.60 → top_k 压到 6、记忆 3 条
    其余       → 使用原 top_k、记忆 5 条
```

**token 估算** `estimate_tokens`：无 tokenizer 的保守启发式——中文按 1 token/字，其余非空白字符按 4 字符/token。

**会话摘要**：压缩由上下文模型执行（`chat_context(task="compaction")`，输出预算 2000 token），摘要上限 8000 字符；组装 prompt 时取最新 1 条摘要 + 最近 24 条原始消息。用户端流式问答会在压缩前推送 `status` 事件「正在整理此前对话…」。

### 4. LLM 网关角色模型

```
llm_gateway（全局单例，按 Agent 初始化）
    │
    ├── _primary_client   主模型       —— 正常问答
    ├── _fallback_clients 降级模型列表  —— 主模型失败后依次尝试
    └── _context_client   上下文模型    —— 问题重写 / 会话压缩
         │
         ├── chat_context(task="rewrite")     超时=context_rewrite_timeout_seconds(10s)
         └── chat_context(task="compaction")  超时=context_compaction_timeout_seconds(25s)
```

- **角色互斥**：一个 LLM 配置只能选择主模型 / 降级模型 / 重写压缩模型之一；每个 Agent 有唯一上下文模型（全局配置自动补充）。
- **回退**：`chat` 主→降级→全部失败抛错；`chat_stream` 仅在尚未输出任何内容时允许切模型，已输出则保持流一致；`chat_context` 缺省回退主模型。
- **离线兜底**：生成器捕获全部失败后用 `degradation_manager` 的离线提示语，标记 `model_used="offline"`、`degraded=True`。

### 5. 认证与访问控制

- **两种角色、两套 Cookie**：管理员 `zhida_admin_session`（8 小时）/ 用户 `zhida_user_session`（7 天），均为 `HttpOnly + SameSite=Strict` 的 host-only Cookie，互不携带。
- **管理员注册**：首次部署开放注册唯一管理员（固定主键原子插入互斥，防并发重复创建）；生产环境不提供默认账号密码。
- **用户激活码**：24 位随机字符，登录时 HMAC-SHA256 校验哈希，明文 AES-GCM 加密存储仅供管理员重复制，**领取后密文销毁**。
- **密码哈希**：scrypt（n=2¹⁶、r=8、p=1、maxmem=128MB），存储格式 `scrypt$salt$digest`，验证时兼容旧哈希（n=2¹⁴）并用常量时间比较。
- **会话续期**：剩余有效期低于完整周期 1/3 时滑动续期（Cookie 值不变），登录时撤销同一主体的旧会话。
- **图形验证码**：5 字符 SVG、5 分钟过期、最多 5 次尝试后销毁；用户/管理员/注册各自限流（5-10 次/15 分钟/IP）。
- **维护模式**：`development_mode` 开启后用户端问答返回 503、不消耗额度；可在管理台系统信息页切换，进程内生效。

### 6. 记忆层与缓存层

**记忆层（Mem0）**：向量库复用项目 ChromaDB（collection `zhida_memory`），LLM 配置取自主模型、embedder 取自云端向量配置。支持 `user_id` / `agent_id` / `run_id` 多级隔离。自动抽取事实/偏好/关系，自动更新、合并、删除矛盾记忆；初始化惰性、失败自动降级。

**缓存层级**：

```
L1: 内存字典（进程内，TTL 3600s）── 最快
    │
    ▼
L2: diskcache（SQLite 持久化，跨进程）
    │
    ▼
L3: 实际 LLM/检索调用（最慢）
```

- 问答答案缓存键含 agent、user、历史哈希以隔离，命中回填 L1、写入双写。
- **请求合并** `qa_request_coalescer`：同上下文并发请求只执行一次检索与模型调用（进程内幂等，非持久化）。
- **降级管理** `DegradationManager`：按服务追踪 FULL/DEGRADED/MINIMAL/OFFLINE，`execute_with_fallback` 主策略→降级→兜底。
- **限流** `RateLimiter`：令牌桶 + 滑动窗口 + 相同问题冷却（300s）+ 静默时段，私聊放宽 3 倍。

### 7. 可观测性（Langfuse）

```
generator 完成回答后
    │
    ▼
observe_qa()（fire-and-forget，asyncio.create_task，异常只打 warning）
    │
    ├── trace "rag-answer": input 问题 / output 答案 / metadata(agent_id,
    │       retrieval_time, generation_time, web_search_count, degraded)
    ├── span "retrieval": 检索块明细（rank/document/parent_id/score/content 前1200字，
    │       供「无关引用」评估）
    └── generation "answer": model / output / usage token
```

- **配置双层**：环境变量 `LANGFUSE_*` 作初始值，数据库 `ObservabilityConfig`（id=1 单套、密钥加密）优先。
- **安全**：host 固定校验为 `https://cloud.langfuse.com`，非可信域名拒绝上报。
- **在线评测**：`online_evaluation_enabled` 开启后把完整评分材料（问题 + 检索证据）放入 trace，供云端 Judge 评分。

### 8. 网络检索（可选）

RAG 未命中补充：`_needs_web_supplement` 检测本地证据缺口（显式联网指令 / 通用释义 / 外部事实意图 / 独立文档数 <2）后触发 `web_search_service`，支持 Tavily / Exa / DuckDuckGo / Bing RSS，结果并入上下文。配置在管理台「网络检索」页或 `/admin/web-search` API。

---

## 三、数据模型

### 核心实体关系

```
Agent (1) ──┬── (N) KnowledgeBase (可独立存在，agent_id 可空，支持动态挂载/解绑)
            │
            ├── (N) LLMConfig（主/降级/上下文 三角色，agent_id 可空=全局）
            │
            └── (N) Conversation（用户站会话，含滚动摘要）
                    │
                    └── (N) QAHistory（问答历史）

AccessCode (N) ──┬── (N) Agent（AccessCodeAgent 多对多绑定）
                 ├── (N) AccessCodeDailyUsage（每日额度，并发原子扣减）
                 └── 1 AnonymousUser（绑定一个匿名用户身份）

ObservabilityConfig (1) ── Langfuse 单套配置（加密密钥、在线评测开关、最近连接测试）

AdminUser（唯一管理员，首次注册）
AdminRegistrationLock（固定 id=1，注册互斥锁）

KnowledgeBase (1) ── (N) Document ── (N) DocumentChunk (父块)
        │                                   │
        │                                   ├── ChromaDB 子块向量（parent_id 关联）
        │                                   └── metadata_json (TextChunk 元数据)
        └── 统计：document_count, chunk_count, parent_chunk_count, total_size_bytes
```

### 关键字段

**Agent**
- `persona_preset`: professional / tutor / friendly / direct / custom
- `persona_custom_instruction`: 自定义人格提示词
- `context_window_k`: 上下文窗口（K tokens），默认 64，范围 32-256
- `status`: running / stopped / error；`is_active`: 是否参与问答

**LLMConfig**
- 角色：`is_primary` / `is_fallback` / `is_context_model`（互斥，每 Agent 唯一上下文模型）
- 超时：`context_rewrite_timeout_seconds`(10) / `context_compaction_timeout_seconds`(25)
- 限流：`max_tokens_per_request`(4096) / `max_requests_per_minute`(30) / `max_tokens_per_minute` / `max_tokens_per_day`
- `api_key`：AES-256-GCM 加密存储（密钥派生自机器指纹）

**Conversation**
- `id`(String 48), `owner_type` / `owner_id`, `agent_id`
- `context_summary`：滚动会话摘要
- `summarized_through_history_id`：已摘要到的历史游标（默认 0）

**AccessCode**
- `code_hash`(HMAC-SHA256 唯一), `code_hint`(明文后 8 位), `code_ciphertext`(AES-GCM，领取后销毁)
- `daily_question_limit`(默认 50), `status`: active / claimed / expired / revoked

---

## 四、认证与激活流程

### 首次部署（管理员注册）

```
前端                          后端
 │  1. 访问管理台，选择"注册管理员"    │
 │──────────────────────────────►│
 │  2. 获取图形验证码             │
 │◄──────────────────────────────│
 │  3. 提交 账号+密码+验证码       │
 │──────────────────────────────►│  4. 验证码校验 + 密码 scrypt 哈希
 │                               │  5. INSERT OR IGNORE admin_registration_locks (id=1)
 │                               │     竞争成功才继续，否则 409
 │  6. 签发管理员 Cookie          │
 │◄──────────────────────────────│
```

### 用户激活

```
管理员创建激活码 → 用户访问用户站 → 输入激活码+验证码
    → 激活码原子领取（并发防重）→ 签发用户 Cookie → 绑定匿名用户身份
    → 历史会话/长期记忆/每日额度与该身份绑定
```

重置登录（用户丢失 Cookie）：管理员在管理台换发新激活码并撤销旧设备会话，用户历史保留；删除激活码则级联清理该用户会话、问答与记忆。

---

## 五、部署拓扑

```
浏览器 ──HTTPS──► Nginx（反向代理，保留 Host / 覆盖转发头）
                     │
          ┌──────────┴───────────┐
          │ /api/ 代理            │  静态前端由后端按 Host 提供
          ▼                      │  （admin.example.com → 管理台前端
    FastAPI 后端 (18900)          │    app.example.com → 用户站前端）
          │                      │
          ├── SQLite / ChromaDB / diskcache（数据目录）
          └── 外部：LLM / Embedding / Langfuse / Tavily(Exa) / 飞书
```

- 认证 Cookie 为 host-only，用户站不携带管理员会话 Cookie。
- `ZHIDA_TRUSTED_PROXY_IPS` 只信任明确配置的反代 IP 写入 `X-Real-IP` / `X-Forwarded-Proto`，防客户端伪造真实 IP。
- 生产必须 HTTPS（`AUTH_REQUIRE_HTTPS=true`），公网 HTTP 请求被拒绝，并下发 HSTS。
