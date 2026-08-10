# 智答引擎（ZhiDa Engine）API 文档

> 本文档描述当前部署版本的真实 API。渠道（QQ/微信）、群聊自动学习相关接口为历史设计，当前版本未注册任何渠道路由。

Base URL: `/api/v1`

---

## 认证方式

除标注「公开」的端点外，所有端点都需要登录会话。系统有两种角色，各自使用独立的 HttpOnly Cookie：

| 角色 | Cookie 名称 | 有效期 | 登录方式 |
|------|------------|--------|----------|
| 管理员 | `zhida_admin_session` | 8 小时（滑动续期） | 账号 + 密码 + 图形验证码 |
| 用户 | `zhida_user_session` | 7 天（滑动续期） | 一次性激活码 |

Cookie 属性：`HttpOnly + SameSite=Strict`，无 `domain`（host-only）。管理员端与用户端的 Cookie 互不携带，避免跨站会话泄漏。

大多数管理类路由（`llm` / `embedding` / `vision` / `knowledge` / `agent` / `qa` / `admin`）在注册时统一挂载 `require_admin` 依赖；`auth` 与 `user` 模块在各自端点内校验身份。

---

## 目录

1. [认证模块 auth](#1-认证模块-auth)
2. [用户站模块 user](#2-用户站模块-user)
3. [LLM 配置 llm](#3-llm-配置-llm)
4. [向量化配置 embedding](#4-向量化配置-embedding)
5. [视觉模型配置 vision](#5-视觉模型配置-vision)
6. [知识库管理 knowledge](#6-知识库管理-knowledge)
7. [Agent 管理 agent](#7-agent-管理-agent)
8. [问答服务 qa](#8-问答服务-qa)
9. [系统管理 admin](#9-系统管理-admin)
10. [附录 A：配置项参考](#附录-a配置项参考)
11. [附录 B：错误码](#附录-b错误码)

---

## 1. 认证模块 auth

### 1.1 获取图形验证码挑战（公开）

```
GET /auth/captcha?purpose=user|admin
```

获取图形验证码挑战，返回 SVG 图片地址。验证码 5 个字符、5 分钟过期、最多尝试 5 次后销毁。

**请求参数：**
- `purpose`: `user` / `admin`

**响应示例：**
```json
{
  "captcha_id": "uuid-string",
  "image_url": "/api/v1/auth/captcha/{captcha_id}/image",
  "expires_in": 300
}
```

### 1.2 获取验证码图片（公开）

```
GET /auth/captcha/{captcha_id}/image
```

返回 `image/svg+xml` 类型的验证码图片。

### 1.3 用户登录（激活码领取）（公开）

```
POST /auth/user/login
```

用户使用一次性激活码登录。激活码在首次登录后立即变为「已激活」，完整码密文被销毁，无法被第二个人使用。

**请求体：**
```json
{
  "captcha_id": "uuid-string",
  "captcha_answer": "a1b2c",
  "access_code": "XXXX-XXXX-XXXX-XXXX-XXXX-XXXX"
}
```

**响应：** 写入 `zhida_user_session` Cookie，返回 `{ "role": "user", "user_id": 1 }`。

### 1.4 管理员登录（公开）

```
POST /auth/admin/login
```

**请求体：**
```json
{
  "captcha_id": "uuid-string",
  "captcha_answer": "a1b2c",
  "username": "admin",
  "password": "********"
}
```

字段约束：`username` 3-100 字符，`password` 6-200 字符。防爆破：同一 IP 每 15 分钟最多 5 次失败。

**响应：** 写入 `zhida_admin_session` Cookie，返回 `{ "role": "admin", "username": "admin" }`。

### 1.5 管理员首次注册（公开）

```
POST /auth/admin/register
```

首次部署时注册唯一管理员，注册成功即签发会话。已有管理员则返回 409。并发注册通过固定主键的原子插入互斥，避免重复创建。

**请求体：**
```json
{
  "captcha_id": "uuid-string",
  "captcha_answer": "a1b2c",
  "username": "admin",
  "password": "********"
}
```

约束：`username` ≥3 字符，`password` ≥8 位。密码使用 scrypt（n=2¹⁶、r=8、p=1、maxmem=128MB）哈希存储。

**响应：** 写入管理员会话，返回 `{ "role": "admin", "username": "admin" }`。

### 1.6 登出（公开）

```
POST /auth/logout
```

删除管理员与用户会话并清除对应 Cookie，返回 `{ "success": true }`。

### 1.7 当前身份（公开）

```
GET /auth/me?role=admin|user
```

返回当前登录身份。可选 `role` 参数用于明确校验角色（本地双端口调试时按 Origin 判定）。

**响应示例：**
```json
{ "role": "admin", "id": 1, "username": "admin" }
```

### 1.8 兑换码管理（require_admin）

以下端点均为管理员专用，前缀 `/auth/admin/access-codes`。

#### 创建激活码

```
POST /auth/admin/access-codes
```

**请求体：**
```json
{
  "agent_ids": [1, 2],
  "daily_question_limit": 50,
  "note": "新用户",
  "expires_days": 30,
  "count": 1
}
```

`agent_ids`（≥1）必填；`daily_question_limit` 1-10000，默认 50；`count` 1-100，默认 1。激活码为 24 位随机字符（去除 0/1/O/I），4 位一组短横线分隔；明文完整码仅返回一次。

**响应示例：**
```json
{
  "items": [{ "id": 1, "access_code": "XXXX-XXXX-XXXX-XXXX-XXXX-XXXX", "code_hint": "••••-abcd1234" }]
}
```

#### 列出激活码

```
GET /auth/admin/access-codes
```

返回全部激活码（含脱敏信息与已绑定的 Agent）：

```json
{
  "items": [
    {
      "id": 1, "code_hint": "••••-abcd1234", "status": "active",
      "daily_question_limit": 50, "usage_today": 3, "expires_at": null,
      "claimed_at": null, "note": null, "created_at": "...",
      "agents": [{ "id": 1, "name": "产品助手" }]
    }
  ]
}
```

`status` 取值：`active`（待激活）/ `claimed`（已激活）/ `expired`（已过期）/ `revoked`（已停用）。

#### 按用户提供的旧码定位

```
POST /auth/admin/access-codes/lookup
```

**请求体：** `{ "access_code": "用户输入的完整码" }`。不回显明文，只返回该记录的脱敏信息，用于管理员查询用户丢失的激活码。

#### 复制未领取激活码

```
POST /auth/admin/access-codes/{code_id}/copy
```

复制未领取（active）的激活码。领取后密文已销毁，无法再读；若密文不可解密则自动轮换新码。

**响应：** `{ "id": 1, "access_code": "...", "code_hint": "...", "rotated": false }`

#### 批量复制

```
POST /auth/admin/access-codes/copy/batch
```

**请求体：** `{ "ids": [1, 2] }`；响应 `{ "items": [{ "id": 1, "access_code": "..." }], "rotated_count": 0, "unavailable_count": 0 }`。

#### 重置登录（换发激活码）

```
POST /auth/admin/access-codes/{code_id}/reset-activation
```

用户丢失 Cookie 时换发一枚新的单次激活码，并撤销该用户所有设备的旧会话。用户历史与会话记录保留。

**响应：** `{ "id": 1, "access_code": "XXXX-...-XXXX", "code_hint": "••••-abcd1234" }`

#### 修改每日额度

```
PUT /auth/admin/access-codes/{code_id}/daily-limit
```

**请求体：** `{ "daily_question_limit": 100 }`。不能低于该用户今日已用次数。

#### 停用激活码

```
POST /auth/admin/access-codes/{code_id}/revoke
```

停用后用户立即无法继续访问，并撤销其会话。响应 `{ "success": true, "id": 1 }`。

#### 删除激活码

```
DELETE /auth/admin/access-codes/{code_id}
```

永久删除激活码，级联清理该用户的会话、问答记录与记忆。响应 `{ "success": true, "id": 1 }`。

#### 批量删除

```
POST /auth/admin/access-codes/batch/delete
```

**请求体：** `{ "ids": [1, 2] }`；响应 `{ "success": true, "deleted": 2 }`。

---

## 2. 用户站模块 user

> 用户站是独立的前端站点（`ZHIDA_USER_APP_HOSTS` 指定的主机名），仅含对话功能。以下端点均依赖 `require_user`。

### 2.1 获取可用 Agent 列表

```
GET /user/agents
```

返回当前用户激活码授权的 Agent 列表：`{ "items": [{ "id": 1, "name": "产品助手", "description": "...", "avatar": "..." }] }`。

### 2.2 用户账户信息

```
GET /user/me
```

**响应：**
```json
{
  "remaining_today": 47,
  "development_mode": false
}
```

`development_mode` 为维护模式状态：维护期间用户端问答会被拒绝。

### 2.3 会话列表

```
GET /user/conversations
```

返回当前用户的历史会话：`{ "items": [{ "id": "...", "agent_id": 1, "title": "...", "updated_at": "..." }] }`。

### 2.4 会话详情

```
GET /user/conversations/{conversation_id}
```

返回单会话的消息记录（校验归属）：

```json
{
  "conversation": { "id": "...", "agent_id": 1, "title": "..." },
  "items": [{ "id": 1, "question": "...", "answer": "...", "sources": [], "created_at": "..." }]
}
```

### 2.5 流式问答（SSE）

```
POST /user/chat/stream
```

**请求体：**
```json
{
  "agent_id": 1,
  "question": "退款流程是什么？",
  "conversation_id": null,
  "response_detail": "concise"
}
```

- `question` ≤2000 字符；`response_detail` 为 `concise` / `detailed`
- 维护模式开启时返回 503；超额度/超限流返回 429
- 会话开始前会按上下文占用率自动压缩/裁剪历史（详见架构文档）

**SSE 事件：**

| 事件 | 内容 |
|------|------|
| `status` | `{ "detail": "正在整理此前对话…", "stage": "compacting" }`（触发会话压缩时） |
| `delta` | `{ "content": "增量文本" }` |
| `done` | `{ "conversation_id": "...", "sources": [...], "remaining_today": 47 }` |
| `error` | `{ "detail": "通用错误描述" }` |

---

## 3. LLM 配置 llm

> 整组 require_admin。三个模型角色互斥：主模型（`is_primary`）、降级模型（`is_fallback`）、重写/压缩模型（`is_context_model`），一个配置只能选择其一。

### 3.1 获取厂商模板

```
GET /llm/providers
```

返回厂商模板列表，按 `{ cloud, local, custom }` 分组。

### 3.2 自动填充厂商信息

```
POST /llm/providers/autofill
```

**请求体：** `{ "provider_id": "deepseek" }`；自动填充 base_url 与模型列表。

### 3.3 获取配置列表

```
GET /llm/configs?agent_id={agent_id}
```

`agent_id` 省略时返回全局配置（`agent_id` 为 NULL）。

**响应：** `list[LLMConfigOut]`，字段含 `id, agent_id, provider_id, provider_name, base_url, model_name, api_key(脱敏), is_primary, is_fallback, is_context_model, context_rewrite_timeout_seconds, context_compaction_timeout_seconds, is_active, extra_config, max_tokens_per_request, max_requests_per_minute, max_tokens_per_minute, max_tokens_per_day, tokens_used_today, requests_today, last_test_at, last_test_success, created_at, updated_at`。

### 3.4 创建配置

```
POST /llm/configs
```

**请求体：**
```json
{
  "agent_id": null,
  "provider_id": "deepseek",
  "provider_name": "DeepSeek",
  "base_url": "https://api.deepseek.com/v1",
  "model_name": "deepseek-chat",
  "api_key": "sk-xxx",
  "is_primary": true,
  "is_fallback": false,
  "is_context_model": false,
  "context_rewrite_timeout_seconds": 10,
  "context_compaction_timeout_seconds": 25,
  "is_active": true,
  "max_tokens_per_request": 4096,
  "max_requests_per_minute": 30
}
```

- `provider_id = "ollama"` 已被禁用（不再支持本地模型）
- 角色互斥：主模型、降级模型、重写/压缩模型不能同时选择
- 设为主模型/上下文模型时，会先取消该 Agent 同角色的其他配置

### 3.5 更新配置

```
PUT /llm/configs/{config_id}
```

字段与创建相同（可选）。传空的 `api_key` 不会修改已有密钥。

### 3.6 删除配置

```
DELETE /llm/configs/{config_id}
```

响应 `{ "message": "已删除", "id": 1 }`。

### 3.7 测试任意连接

```
POST /llm/test-connection
```

**请求体：** `{ "base_url": "...", "api_key": "sk-xxx", "model_name": "deepseek-chat" }`

**响应：** `{ "success": true, "message": "...", "latency_ms": 123, "model": "..." }`。

### 3.8 测试已保存配置

```
POST /llm/configs/{config_id}/test
```

测试已保存的配置并记录结果（`last_test_at` / `last_test_success`）。

---

## 4. 向量化配置 embedding

> 整组 require_admin。当前仅支持云端 Embedding（OpenAI 兼容接口），本地模式已移除。

### 4.1 配置档案列表

```
GET /embedding/profiles
```

返回云端向量配置卡片列表（含 `is_primary, cloud_model, cloud_dimension`）。

### 4.2 创建配置档案

```
POST /embedding/profiles
```

**请求体：**
```json
{
  "name": "硅基流动",
  "provider_id": "siliconflow",
  "mode": "cloud",
  "cloud_base_url": "https://api.siliconflow.cn/v1",
  "cloud_api_key": "sk-xxx",
  "cloud_model": "BAAI/bge-large-zh-v1.5",
  "cloud_dimension": 1024,
  "is_active": true
}
```

首个可用配置自动设为主配置。

### 4.3 更新配置档案

```
PUT /embedding/profiles/{profile_id}
```

主配置修改模型或维度时需重建已有向量索引。

### 4.4 删除配置档案

```
DELETE /embedding/profiles/{profile_id}
```

主配置返回 409。

### 4.5 测试配置

```
POST /embedding/profiles/{profile_id}/test
```

**响应：** `{ "success": true, "message": "...", "latency_ms": 123, "dimension": 1024 }`。

### 4.6 设为主配置

```
POST /embedding/profiles/{profile_id}/activate?rebuild=true
```

`rebuild` 指示是否需要重建已有索引。

### 4.7 厂商模板

```
GET /embedding/providers
POST /embedding/providers/autofill
```

### 4.8 当前配置（兼容旧接口）

```
GET /embedding/config
PUT /embedding/config
POST /embedding/test
```

读取 / 更新当前生效的向量化配置；`POST /embedding/test` 测试任意云端连接。

---

## 5. 视觉模型配置 vision

> 整组 require_admin。用于网页导入、图片理解等场景的视觉模型。

### 5.1 配置列表

```
GET /vision/configs
```

返回 `list[VisionConfigOut]`，字段含 `id, name, is_primary, is_fallback, enabled, base_url, model_name, api_key(脱敏), last_test_*`。

### 5.2 创建 / 更新配置

```
POST /vision/configs
PUT /vision/configs/{config_id}
```

**请求体：** `{ "name": "...", "enabled": true, "base_url": "...", "model_name": "...", "api_key": "sk-xxx", "is_primary": true, "is_fallback": false }`。

### 5.3 删除配置

```
DELETE /vision/configs/{config_id}
```

主配置返回 409。

### 5.4 测试图片输入连通性

```
POST /vision/configs/{config_id}/test
```

响应 `{ "success": true, "message": "..." }`。

### 5.5 兼容单配置接口

```
GET /vision/config
PUT /vision/config
```

兼容旧前端的单配置读取 / 更新。

---

## 6. 知识库管理 knowledge

> 整组 require_admin。

### 6.1 获取知识库列表

```
GET /knowledge/bases?agent_id={agent_id}
```

`agent_id` 可选，过滤指定 Agent 挂载的知识库。

### 6.2 创建知识库

```
POST /knowledge/bases
```

**请求体：** `{ "agent_id": null, "name": "我的知识库", "description": "..." }`。`agent_id` 为空表示创建独立知识库。

### 6.3 获取独立知识库列表

```
GET /knowledge/bases/independent
```

返回未挂载到任何 Agent 的独立知识库列表。

### 6.4 获取知识库详情

```
GET /knowledge/bases/{kb_id}
```

### 6.5 更新知识库

```
PUT /knowledge/bases/{kb_id}
```

**请求体：** `{ "name"?, "description"?, "is_active"? }`。

### 6.6 删除知识库

```
DELETE /knowledge/bases/{kb_id}
```

按「Chroma 集合 → 本地文件 → SQLite 记录」顺序清理。

### 6.7 重建向量索引

```
POST /knowledge/bases/{kb_id}/rebuild-index
```

备份后异步重建 Chroma 索引。响应 `{ "success": true, "message": "...", "backup": "...", "document_count": 10 }`。

### 6.8 挂载 / 解绑知识库

```
POST /knowledge/bases/{kb_id}/attach
POST /knowledge/bases/{kb_id}/detach?agent_id={agent_id}
```

**attach 请求体：** `{ "agent_id": 1 }`。解绑后变为独立知识库。

**响应：** `{ "success": true, "message": "挂载成功", "kb_id": 1, "agent_id": 1 }`。

### 6.9 上传文档

```
POST /knowledge/bases/{kb_id}/upload
Content-Type: multipart/form-data
```

**请求参数：** `file`（文档文件）。

**支持的格式：**
- 基础格式：`.pdf` `.docx` `.doc` `.xlsx` `.xls` `.txt` `.md` `.csv` `.json` `.xml`
- 启用 MinerU 额外支持：`.pptx` `.ppt` `.epub` `.html` `.htm` `.png` `.jpg` `.jpeg` `.bmp` `.tiff` `.webp`

**上传前预检（格式校验）：** 基于文件头 magic bytes 校验真实类型（防扩展名伪装）→ 扩展名匹配 → 文件名清洗 → 文件完整性（PDF %%EOF、ZIP 校验和）。失败返回格式：

```json
{ "detail": "文件类型不匹配: 扩展名声称 .pdf，实际检测为 binary" }
```

**文档处理流程：** 上传 → 预检 → 解析（MinerU 可选 / 本地）→ 质量检查 → 父子块切分（子块 200 字符 / 重叠 50）→ 父块入 SQLite、子块向量化入 ChromaDB。解析在后台异步执行。

**文档状态：** `pending`（等待）/ `processing`（处理中）/ `completed`（完成）/ `error`（失败）。处理中的进度经文档列表的 `status` / `processing_stage` / `processing_attempts` 字段暴露；向量化索引失败不影响 `completed` 状态（在 `error_message` 中提示）。

### 6.10 获取文档列表

```
GET /knowledge/documents?agent_id={agent_id}&kb_id={kb_id}
```

返回 `{ "total": 10, "items": [{ "id": 1, "filename": "...", "status": "completed", "processing_stage": "...", "failed_stage": null, "chunk_count": 50, "parent_chunk_count": 15 }] }`。

### 6.11 获取待审批正文

```
GET /knowledge/documents/{document_id}/content
```

返回待审批外部来源资料的入库正文（上限 300KB）：`{ "id": 1, "filename": "...", "source_type": "...", "source_url": "...", "content": "...", "truncated": false }`。

### 6.12 审批外部来源文档

```
POST /knowledge/documents/approve
```

**请求体：** `{ "document_ids": [1, 2] }`；响应 `{ "approved": 2, "skipped": 0 }`。

### 6.13 保留来源被移除的文档

```
POST /knowledge/documents/{document_id}/retain-source-removed
```

### 6.14 取消文档处理

```
POST /knowledge/documents/{document_id}/cancel
```

取消待处理 / 处理中文档并清理中间索引。响应 `{ "success": true, "message": "..." }`。

### 6.15 删除文档

```
DELETE /knowledge/documents/{document_id}
```

删除本地文件、SQLite 记录、父块记录与 ChromaDB 向量索引，并更新统计。处理中返回 409。

### 6.16 批量删除文档

```
POST /knowledge/documents/batch-delete
```

**请求体：** `{ "document_ids": [1, 2] }`；处理中的文档跳过。响应 `{ "removed": 1, "skipped": 1, "cleanup_pending": 0 }`。

### 6.17 清除失败文档

```
DELETE /knowledge/bases/{kb_id}/failed-documents
```

清除失败文档及残留向量。响应 `{ "success": true, "removed": 2, "retained": 0 }`。

### 6.18 网页导入

```
POST /knowledge/bases/{kb_id}/web/import
```

**请求体：** `{ "url": "https://example.com/article" }`（12-2000 字符）。后台抓取 + LLM 保真重写 + 视觉识别。

**响应：** `{ "document": {...}, "duplicate": false }`。

### 6.19 飞书数据源

```
GET /knowledge/feishu/config
PUT /knowledge/feishu/config
POST /knowledge/feishu/config/test
```

读取 / 更新飞书配置（`{ enabled, app_id, app_secret?, last_test_* }`）并测试连接。

### 6.20 飞书文档导入

```
POST /knowledge/bases/{kb_id}/feishu/import
GET /knowledge/feishu/imports/{job_id}
```

**import 请求体：** `{ "url": "...", "max_nodes": 50 }`（1-100）。返回 `{ "job_id": "..." }`；任务进度查询返回 `{ "id": "...", "status": "processing", "total": 20, "processed": 8, "imported": 6, "duplicate": 2, "error_message": null, "logs": [...] }`。同一正文基于 SHA-256 自动去重。

### 6.21 知识库统计

```
GET /knowledge/stats?agent_id={agent_id}
```

返回 `{ "total_documents": 10, "total_chunks": 100, "total_size_mb": 5.2, "documents_by_type": {...}, "documents_by_status": {...}, "last_upload_at": "..." }`。

### 6.22 知识库优化

```
POST /knowledge/optimize
```

**请求体：** `{ "agent_id": 1, "remove_duplicates": true, "merge_small_chunks": false }`；响应 `{ "success": true, "message": "...", "chunks_before": 100, "chunks_after": 80, "removed_count": 20 }`。

---

## 7. Agent 管理 agent

> 整组 require_admin。

### 7.1 获取 Agent 列表

```
GET /agents
```

返回 `{ "total": 5, "items": [AgentOut] }`。

### 7.2 创建 Agent

```
POST /agents
```

**请求体：**
```json
{
  "name": "产品助手",
  "description": "回答产品与交付问题",
  "avatar": null,
  "persona_preset": "professional",
  "persona_custom_instruction": null,
  "context_window_k": 64
}
```

- `persona_preset`: `professional` / `tutor` / `friendly` / `direct` / `custom`；`custom` 时需提供 `persona_custom_instruction`
- `context_window_k`: 32-256，默认 64（K tokens 的上下文窗口）
- 新建后默认 `stopped` 状态

### 7.3 获取 Agent 详情

```
GET /agents/{agent_id}
```

`AgentOut` 含 `id, name, description, status, is_active, persona_preset, persona_custom_instruction, context_window_k, created_at, updated_at`。

### 7.4 更新 Agent

```
PUT /agents/{agent_id}
```

字段同创建（均可选）。

### 7.5 删除 Agent

```
DELETE /agents/{agent_id}
```

级联解绑知识库关联。响应 `{ "message": "...", "id": 1 }`。

### 7.6 启动 / 停止 Agent

```
POST /agents/{agent_id}/start
POST /agents/{agent_id}/stop
```

启动会创建沙箱并配置网络白名单，置 `running`；停止销毁沙箱。**问答接口只接受已启用（active）的 Agent。**

### 7.7 Agent 统计

```
GET /agents/{agent_id}/stats
```

返回 `{ "agent_id": 1, "agent_name": "...", "status": "running", "today_messages": 10, "today_answers": 8, "today_learned": 0, "success_rate": 0.9, "avg_response_time_ms": 684.2, "total_knowledge_chunks": 100, "last_active_at": "..." }`。

### 7.8 沙箱统计

```
GET /agents/sandboxes
GET /agents/{agent_id}/sandbox
```

前者返回所有 Agent 沙箱总体统计；后者返回单个 Agent 沙箱资源统计（无沙箱时返回 `{ "agent_id": 1, "status": "no_sandbox", "message": "..." }`）。

---

## 8. 问答服务 qa

> 整组 require_admin。对外接入请使用 `/api/v1/qa/ask`（详见 README「作为服务接入其他应用」）。

### 8.1 提问（完整 RAG 问答）

```
POST /qa/ask
```

**请求体：**
```json
{
  "agent_id": 3,
  "question": "退款流程是什么？",
  "chat_id": "web-session-a8f2",
  "chat_type": "private",
  "user_id": "external-user-42",
  "stream": false,
  "response_detail": "concise"
}
```

执行：请求合并 → 缓存命中检查 → 记忆检索 → 问题改写 → 多路混合检索 → 联网补充（可选）→ 生成。

**响应示例：**
```json
{
  "question": "退款流程是什么？",
  "answer": "……",
  "sources": [
    { "document_name": "售后政策.md", "chunk_text": "……", "score": 0.82, "source_type": "document" }
  ],
  "confidence": 0.8,
  "response_time_ms": 684.2,
  "model_used": "your-model-name",
  "from_cache": false
}
```

### 8.2 流式问答（管理端）

```
POST /qa/stream
```

请求体同 `8.1`。SSE 事件：`delta` / `status` / `done` / `error`，`done` 携带 `{ sources, response_time_ms, model_used }`。

### 8.3 问答历史

```
GET /qa/history?agent_id={agent_id}&page=1&page_size=20
```

返回 `{ "total": 100, "items": [QAHistoryOut] }`。

### 8.4 删除历史记录

```
DELETE /qa/history/{qa_id}
```

响应 `{ "message": "...", "id": 1 }`。

### 8.5 反馈

```
POST /qa/feedback
```

**请求体：** `{ "qa_id": 1, "feedback": "useful", "comment": "可选" }`。`feedback` 为 `useful` / `useless`。

---

## 9. 系统管理 admin

> 整组 require_admin。

### 9.1 系统信息

```
GET /admin/system-info
```

不暴露密钥。响应 `{ "app_name": "智答引擎", "app_version": "0.1.0", "python_version": "3.11.x", "platform": "Darwin", "data_dir": "...", "api_address": "...", "cpu_cores": 8, "memory_gb": 16.0, "storage_type": "sqlite", "resource_profile": "..." }`。

### 9.2 组件健康检查

```
GET /admin/component-health
```

检查 sqlite / chroma / embedding / vision 可用性（无副作用）：`{ "items": [{ "key": "sqlite", "name": "...", "available": true, "message": "..." }], "checked_at": "..." }`。

### 9.3 模块开关（含维护模式）

```
GET /admin/settings
PUT /admin/settings
```

**响应 / 请求体：**
```json
{ "enable_source_citation": true, "enable_rate_limit": true, "development_mode": false }
```

`development_mode` 为开发维护模式：开启后用户端问答返回 503，且不会消耗用户额度。更新在进程内生效，重启后回退到 `.env`。

### 9.4 可观测性（Langfuse）

```
GET /admin/observability
PUT /admin/observability
POST /admin/observability/test
DELETE /admin/observability
```

读取 / 更新 Langfuse 可观测性配置（密钥脱敏返回）。`host` 固定为 `https://cloud.langfuse.com`，非可信域名拒绝上报。`online_evaluation_enabled` 开启后会将问题与检索证据提供给云端 Judge 评分。DELETE 停止上报并返回 204。

**更新请求示例：**

```json
{
  "langfuse_enabled": true,
  "langfuse_host": "https://cloud.langfuse.com",
  "langfuse_public_key": "pk-lf-...",
  "langfuse_secret_key": "sk-lf-...",
  "online_evaluation_enabled": true
}
```

密钥字段留空表示保留已保存的值。`POST /admin/observability/test` 使用已保存密钥检测项目连通性；为保护外部连接，该操作有 10 秒冷却。`online_evaluation_enabled` 不会在本地额外调用模型，只会向新产生的根 Trace 写入 `question`、`retrieval_context` 与 `answer`，由 Langfuse 中已启用的 trace Evaluator 异步评分。

### 9.5 网络搜索配置

```
GET /admin/web-search
PUT /admin/web-search
POST /admin/web-search/test
```

网络检索（Tavily / Exa）配置：`{ "enabled": false, "provider": "tavily", "tavily_api_key": "••••", "exa_api_key": "••••", "tavily_configured": false, "exa_configured": false, "max_results": 3 }`。

### 9.6 仪表盘数据

```
GET /admin/dashboard?start_date={date}&end_date={date}
```

返回 `{ "total_agents": 5, "running_agents": 2, "today_messages": 20, "today_answers": 15, "success_rate": 0.9, "total_knowledge_chunks": 500, "total_documents": 30, "cache_hit_rate": 0.4, "today_input_tokens": 10000, "today_output_tokens": 8000, "web_search_count": 3 }`。

### 9.7 模型健康

```
GET /admin/model-health
```

逐个测试 LLM 配置：`{ "chat_models": [{ "name": "...", "role": "primary", "available": true, "message": "..." }], "embedding": { "name": "...", "available": true } }`。

### 9.8 LLM 使用统计

```
GET /admin/llm-usage
```

各 LLM 配置的使用统计（30 秒缓存刷新）。

### 9.9 数据可靠性

```
GET /admin/reliability
POST /admin/reliability/backup
POST /admin/reliability/cleanup-pending
```

只读核验 SQLite / Chroma 数据完整性；手动备份；重试待清理项。

### 9.10 缓存管理

```
GET /admin/cache-stats
POST /admin/clear-cache
```

缓存统计 `{ "hits": 100, "misses": 50, "total": 150, "hit_rate": 0.67, "memory_entries": 10, "disk_entries": 20 }`；清空缓存。

### 9.11 限流配置

```
GET /admin/rate-limit
PUT /admin/rate-limit
```

令牌桶 + 滑动窗口 + 冷却配置：`{ "token_bucket_rate": 10.0, "token_bucket_capacity": 3, "window_size_seconds": 60, "window_max_requests": 5, "question_cooldown_seconds": 300, "silent_period_enabled": true, "private_chat_relaxed": true }`。

### 9.12 资源方案推荐

```
GET /admin/resource-profile
```

返回机器资源推荐方案。

### 9.13 记忆层管理

```
GET /admin/memory/stats
GET /admin/memory/list?user_id=&agent_id=&run_id=&limit=
POST /admin/memory/search
GET /admin/memory/{memory_id}
POST /admin/memory
PUT /admin/memory/{memory_id}
DELETE /admin/memory/{memory_id}
DELETE /admin/memory
GET /admin/memory/history/{memory_id}
```

记忆层的统计、列表、语义搜索、增删改查与变更历史。支持 `user_id` / `agent_id` / `run_id` 多级隔离过滤。

### 9.14 人格预设

```
GET /admin/persona-presets
PUT /admin/persona-presets/{preset_key}
```

人格预设列表与更新（`preset_key` ∈ `professional` / `tutor` / `friendly` / `direct`）。

---

## 附录 A：配置项参考

所有配置通过环境变量（`ZHIDA_` 前缀）+ `backend/.env` 文件管理。

### 应用基础 / 数据库

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ZHIDA_DEBUG` | `false` | 调试模式（生产必须关闭） |
| `ZHIDA_DATA_DIR` | 平台应用数据目录 | SQLite / 向量库 / 缓存根目录 |
| `ZHIDA_DATABASE_URL` | 空 | 空则用 `{DATA_DIR}/zhida_engine.db` |
| `ZHIDA_API_HOST` | `127.0.0.1` | 监听地址 |
| `ZHIDA_API_PORT` | `18900` | 服务端口 |

### 部署 / 信任

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ZHIDA_CORS_ORIGINS` | `http://localhost:5173,...` | 允许的前端源 |
| `ZHIDA_TRUSTED_HOSTS` | `localhost,127.0.0.1,::1` | 受信任主机名 |
| `ZHIDA_USER_APP_HOSTS` | 空 | 用户站主机名（返回独立前端） |
| `ZHIDA_TRUSTED_PROXY_IPS` | `127.0.0.1,::1` | 可信反代 IP（Docker Nginx 常追加 `172.17.0.1`） |

### 认证 / 安全

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ZHIDA_AUTH_SESSION_SECRET` | 空 | 会话签名密钥，**必须 ≥32 位**，否则拒绝服务 |
| `ZHIDA_AUTH_USER_SESSION_DAYS` | `7` | 用户会话有效期 |
| `ZHIDA_AUTH_ADMIN_SESSION_HOURS` | `8` | 管理员会话有效期 |
| `ZHIDA_AUTH_REQUIRE_HTTPS` | `true` | 公网强制 HTTPS |
| `ZHIDA_API_KEY_ENCRYPT_ENABLED` | `true` | API Key 加密存储 |
| `ZHIDA_ADMIN_BOOTSTRAP_USERNAME/PASSWORD` | 空 | 仅 DEBUG 模式创建引导管理员 |

### 向量化 / 缓存

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ZHIDA_EMBEDDING_MODE` | `cloud` | 向量化模式（仅云端） |
| `ZHIDA_EMBEDDING_CLOUD_BASE_URL` | 空 | OpenAI 兼容接口 |
| `ZHIDA_EMBEDDING_CLOUD_API_KEY` | 空 | 云端密钥 |
| `ZHIDA_EMBEDDING_CLOUD_MODEL` | `text-embedding-3-small` | 云端模型 |
| `ZHIDA_CHROMA_PERSIST_DIR` | 空 | 空则用 `{DATA_DIR}/chroma_db` |
| `ZHIDA_CACHE_DIR` | 空 | 空则用 `{DATA_DIR}/cache` |

### 模块开关

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ZHIDA_ENABLE_STREAMING` | `true` | 流式输出 |
| `ZHIDA_ENABLE_SOURCE_CITATION` | `true` | 回答附带来源 |
| `ZHIDA_DEVELOPMENT_MODE` | `false` | 开发维护模式（暂停用户端问答） |

### 可观测性（Langfuse）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ZHIDA_LANGFUSE_ENABLED` | `false` | 总开关（数据库配置优先） |
| `ZHIDA_LANGFUSE_HOST` | `https://cloud.langfuse.com` | 固定云端地址 |
| `ZHIDA_LANGFUSE_PUBLIC_KEY` | 空 | 公钥 |
| `ZHIDA_LANGFUSE_SECRET_KEY` | 空 | 密钥 |
| `ZHIDA_LANGFUSE_ONLINE_EVALUATION_ENABLED` | `false` | 云端在线评测 |

### 网络检索

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ZHIDA_WEB_SEARCH_ENABLED` | `false` | 网络检索总开关 |
| `ZHIDA_WEB_SEARCH_PROVIDER` | `tavily` | tavily / exa |
| `ZHIDA_WEB_SEARCH_API_KEY` | 空 | 密钥 |
| `ZHIDA_WEB_SEARCH_MAX_RESULTS` | `3` | 最大结果数 |

### 限流

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ZHIDA_RATE_LIMIT_TOKEN_RATE` | `10.0` | 令牌桶速率 |
| `ZHIDA_RATE_LIMIT_TOKEN_CAPACITY` | `3` | 桶容量 |
| `ZHIDA_RATE_LIMIT_WINDOW_SIZE` | `60` | 滑动窗口（秒） |
| `ZHIDA_RATE_LIMIT_WINDOW_MAX` | `5` | 窗口内最大请求 |
| `ZHIDA_RATE_LIMIT_COOLDOWN` | `300` | 相同问题冷却（秒） |
| `ZHIDA_RATE_LIMIT_SILENT_ENABLED` | `true` | 静默时段 |
| `ZHIDA_RATE_LIMIT_PRIVATE_RELAXED` | `true` | 私聊放宽 |

### 并发保护

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ZHIDA_QA_MAX_CONCURRENT_STREAMS` | `10` | 最大并发流 |
| `ZHIDA_QA_MAX_STREAM_QUEUE` | `20` | 排队上限 |
| `ZHIDA_QA_STREAM_QUEUE_TIMEOUT_SECONDS` | `45` | 排队超时 |

### MinerU（可选）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ZHIDA_ENABLE_MINERU` | `false` | 总开关（需安装 magic-pdf） |
| `ZHIDA_MINERU_MODE` | `embedded` | embedded / service |
| `ZHIDA_MINERU_BACKEND` | `pipeline` | pipeline / vlm-engine |
| `ZHIDA_MINERU_DEVICE` | `cpu` | 计算设备 |
| `ZHIDA_MINERU_SERVICE_URL` | `http://127.0.0.1:18901` | service 模式地址 |
| `ZHIDA_MINERU_FORMATS` | `pdf` | 处理格式 |
| `ZHIDA_MINERU_FALLBACK_ON_FAILURE` | `true` | 失败降级本地解析 |
| `ZHIDA_MINERU_MAX_FILE_SIZE_MB` | `50` | 超过走本地解析器 |

### 格式校验

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ZHIDA_ENABLE_FORMAT_CHECK` | `true` | 总开关 |
| `ZHIDA_FORMAT_CHECK_STRICT` | `true` | 类型不匹配直接拒绝 |
| `ZHIDA_FORMAT_MIN_TEXT_LENGTH` | `10` | 最小文本长度 |
| `ZHIDA_FORMAT_GARBAGE_THRESHOLD` | `0.5` | 乱码比例阈值 |
| `ZHIDA_FORMAT_AUTO_REJECT_EMPTY` | `true` | 空结果自动拒绝 |
| `ZHIDA_FORMAT_MIN_QUALITY_SCORE` | `10` | 最低质量分（0-100） |

---

## 附录 B：错误码

| HTTP 状态码 | 说明 |
|------------|------|
| 200 | 成功 |
| 204 | 成功（无返回体） |
| 400 | 请求参数错误（含格式校验拒绝） |
| 401 | 未授权 / 会话无效 |
| 403 | 无权限（如访问他人会话） |
| 404 | 资源不存在 |
| 409 | 冲突（知识库已挂载、管理员已存在、处理中文档删除等） |
| 422 | 参数校验失败（Pydantic） |
| 429 | 请求过于频繁（限流 / 额度不足） |
| 500 | 服务器内部错误 |
| 503 | 服务暂不可用（降级 / 维护模式） |

**错误响应格式：**
```json
{ "detail": "错误描述信息" }
```

**常见校验错误示例：**
```json
{"detail": "文件类型不匹配: 扩展名声称 .pdf，实际检测为 binary"}
{"detail": "文件内容为空"}
{"detail": "文档质量检查未通过 (评分 0/100): 文本内容为空"}
{"detail": "主模型、降级模型和重写/压缩模型角色不能同时选择"}
{"detail": "首次注册失败，管理员已存在"}
```
