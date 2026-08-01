# 智答引擎（ZhiDa Engine）API 文档

> 当前交付范围为管理后台与微信小程序。本文中 QQ、Wechaty、NapCat、群聊自动学习相关章节为历史设计，不属于当前部署功能；以 `README.md` 和 `docs/MINIAPP_DEPLOYMENT.md` 为准。

Base URL: `/api/v1`

---

## 目录

1. [LLM 配置](#1-llm-配置)
2. [向量化配置](#2-向量化配置)
3. [知识库管理](#3-知识库管理)
4. [Agent 管理](#4-agent-管理)
5. [渠道管理](#5-渠道管理)
6. [问答服务](#6-问答服务)
7. [系统管理](#7-系统管理)

---

## 1. LLM 配置

### 1.1 获取厂商列表

```
GET /llm/providers
```

获取所有支持的 LLM 厂商模板。

**响应示例：**
```json
{
  "total": 9,
  "items": [
    {
      "type": "openai",
      "name": "OpenAI",
      "base_url": "https://api.openai.com/v1",
      "models": ["gpt-4", "gpt-3.5-turbo"]
    }
  ]
}
```

### 1.2 获取 LLM 配置列表

```
GET /llm/configs?agent_id={agent_id}
```

**请求参数：**
- `agent_id` (可选): Agent ID 过滤

### 1.3 创建 LLM 配置

```
POST /llm/configs
```

**请求体：**
```json
{
  "agent_id": 1,
  "provider_type": "openai",
  "name": "OpenAI 主模型",
  "api_key": "sk-xxx",
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-4",
  "is_primary": true
}
```

### 1.4 更新 LLM 配置

```
PUT /llm/configs/{id}
```

### 1.5 删除 LLM 配置

```
DELETE /llm/configs/{id}
```

### 1.6 测试连接

```
POST /llm/test
```

测试 LLM 配置是否可以正常连接。

**请求体：**
```json
{
  "provider_type": "openai",
  "api_key": "sk-xxx",
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-4"
}
```

### 1.7 使用统计

```
GET /llm/usage
```

---

## 2. 向量化配置

### 2.1 获取厂商列表

```
GET /embedding/providers
```

### 2.2 自动填充厂商信息

```
POST /embedding/providers/autofill
```

根据厂商类型自动填充 base_url 和模型列表。

### 2.3 获取向量化配置

```
GET /embedding/config
```

获取当前向量化配置。配置持久化存储在数据库中（EmbeddingConfig 表），应用启动时自动加载。

### 2.4 更新向量化配置

```
PUT /embedding/config
```

更新向量化配置。配置会保存到数据库，同时运行时动态切换 Embedding 服务实现。

**请求体：**
```json
{
  "mode": "local",
  "model": "BAAI/bge-large-zh-v1.5",
  "device": "cpu",
  "api_key": "",
  "base_url": "",
  "batch_size": 32
}
```

### 2.5 测试连接

```
POST /embedding/test
```

测试向量化配置是否可以正常使用。

---

## 3. 知识库管理

### 3.1 获取知识库列表

```
GET /knowledge/bases?agent_id={agent_id}
```

**请求参数：**
- `agent_id` (可选): Agent ID 过滤

### 3.2 创建知识库

```
POST /knowledge/bases
```

**请求体：**
```json
{
  "name": "我的知识库",
  "description": "知识库描述",
  "agent_id": null
}
```

### 3.3 获取知识库详情

```
GET /knowledge/bases/{kb_id}
```

### 3.4 更新知识库

```
PUT /knowledge/bases/{kb_id}
```

### 3.5 删除知识库

```
DELETE /knowledge/bases/{kb_id}
```

### 3.6 上传文档

```
POST /knowledge/bases/{kb_id}/upload
Content-Type: multipart/form-data
```

**请求参数：**
- `file`: 文档文件

**支持的格式：**
- 基础格式：`.pdf` `.docx` `.doc` `.xlsx` `.xls` `.txt` `.md` `.csv` `.json` `.xml`
- 启用 MinerU 额外支持：`.pptx` `.ppt` `.epub` `.html` `.htm` `.png` `.jpg` `.jpeg` `.bmp` `.tiff` `.webp`

**上传前预检（格式校验）：**
上传文件会经过多层校验：
1. **Magic bytes 检测** — 基于文件头字节验证真实类型，防止扩展名伪装
2. **扩展名匹配** — 真实类型与扩展名不一致时，严格模式直接拒绝上传
3. **文件名清洗** — 移除路径穿越字符和危险字符
4. **文件完整性** — PDF %%EOF 标记、ZIP 校验和检查

校验失败返回格式：
```json
{
  "detail": "文件类型不匹配: 扩展名声称 .pdf，实际检测为 binary"
}
```

**响应示例：**
```json
{
  "id": 1,
  "knowledge_base_id": 1,
  "filename": "document.pdf",
  "file_size": 1024000,
  "file_type": "pdf",
  "status": "completed",
  "chunk_count": 50,
  "parent_chunk_count": 15
}
```

**文档处理流程：**
1. 文件上传到服务器
2. 上传前预检（格式校验 + 文件名清洗 + 损坏检测）
3. DocumentParser 解析文档内容
4. 解析结果质量检查（空内容/乱码/完整度/语言/结构评分）
5. TextSplitter 父子块切分（子块 200 字符 / 重叠 50 / 父块 4 倍）
6. 父块存入 SQLite (document_chunks 表)
7. 子块向量化后存入 ChromaDB

**文档状态说明：**
- `pending`: 等待处理
- `processing`: 处理中
- `completed`: 处理完成（解析和切分成功，向量化可能成功或失败）
- `error`: 处理失败（格式校验拒绝、解析失败或质量检查不通过）

**注意：** 向量化索引失败不会导致文档状态变为 error，会在 `error_message` 字段中提示。文档的 `chunk_count` 字段表示切分后的子块数量，无论是否索引成功都会返回。

### 3.7 获取独立知识库列表

```
GET /knowledge/bases/independent
```

获取未挂载到任何 Agent 的独立知识库列表。

### 3.8 挂载知识库到 Agent

```
POST /knowledge/bases/{kb_id}/attach
```

将独立知识库挂载到指定 Agent。

**请求体：**
```json
{
  "agent_id": 1
}
```

**响应示例：**
```json
{
  "success": true,
  "message": "挂载成功",
  "kb_id": 1,
  "agent_id": 1
}
```

### 3.9 解绑知识库

```
POST /knowledge/bases/{kb_id}/detach
```

将知识库从 Agent 上解绑，变为独立知识库。

**响应示例：**
```json
{
  "success": true,
  "message": "解绑成功",
  "kb_id": 1
}
```

### 3.10 获取文档列表

```
GET /knowledge/documents?kb_id={kb_id}&agent_id={agent_id}
```

**请求参数：**
- `kb_id` (可选): 知识库 ID 过滤
- `agent_id` (可选): Agent ID 过滤

### 3.11 删除文档

```
DELETE /knowledge/documents/{doc_id}
```

删除文档同时删除：
- 本地文件
- 数据库中的 Document 记录
- 数据库中的 DocumentChunk 父块记录
- ChromaDB 中的子块向量索引
- 更新知识库统计（文档数、块数、大小）

### 3.12 知识库统计

```
GET /knowledge/stats?kb_id={kb_id}
```

### 3.13 知识库优化

```
POST /knowledge/optimize
```

---

## 4. Agent 管理

### 4.1 获取 Agent 列表

```
GET /agents
```

### 4.2 创建 Agent

```
POST /agents
```

**请求体：**
```json
{
  "name": "我的助手",
  "description": "AI 助手描述",
  "system_prompt": "你是一个 helpful 的助手",
  "reply_mode": "rag"
}
```

### 4.3 获取 Agent 详情

```
GET /agents/{agent_id}
```

### 4.4 更新 Agent

```
PUT /agents/{agent_id}
```

### 4.5 删除 Agent

```
DELETE /agents/{agent_id}
```

### 4.6 启动 Agent

```
POST /agents/{agent_id}/start
```

### 4.7 停止 Agent

```
POST /agents/{agent_id}/stop
```

### 4.8 Agent 统计

```
GET /agents/{agent_id}/stats
```

---

## 5. 渠道管理

### 5.1 获取渠道配置列表

```
GET /channels?agent_id={agent_id}
```

**请求参数：**
- `agent_id` (可选): Agent ID 过滤

**响应示例：**
```json
{
  "total": 2,
  "items": [
    {
      "id": 1,
      "agent_id": 1,
      "channel_type": "qq",
      "chat_id": "123456",
      "chat_name": "技术交流群",
      "is_listening": true,
      "listen_mode": "all",
      "enable_learning": true,
      "target_users": "[\"10001\",\"10002\"]",
      "auto_reply": true
    }
  ]
}
```

### 5.2 添加渠道

```
POST /channels
```

**请求体：**
```json
{
  "agent_id": 1,
  "channel_type": "qq",
  "chat_id": "123456",
  "chat_name": "技术交流群",
  "listen_mode": "all",
  "enable_learning": true,
  "target_users": "[\"10001\",\"10002\"]",
  "auto_reply": true,
  "reply_with_source": true,
  "auto_mention_on_fail": true,
  "mention_user_ids": "[]"
}
```

**字段说明：**
- `channel_type`: 渠道类型（`qq` / `wechat`）
- `listen_mode`: 监听模式（`all` 全部 / `mentioned` 仅@ / `questions` 仅问题）
- `target_users`: 目标用户列表（JSON 数组字符串，空=监听所有用户）
- `enable_learning`: 是否从聊天中自动学习

### 5.3 更新渠道配置

```
PUT /channels/{channel_id}
```

### 5.4 删除渠道

```
DELETE /channels/{channel_id}
```

### 5.5 开始监听

```
POST /channels/{channel_id}/start-listening
```

### 5.6 停止监听

```
POST /channels/{channel_id}/stop-listening
```

### 5.7 渠道统计

```
GET /channels/{channel_id}/stats
```

---

### 5.8 生成登录二维码

```
POST /channels/{channel_type}/login/qrcode
```

生成渠道登录二维码，用于扫码登录。

**路径参数：**
- `channel_type`: 渠道类型（`qq` / `wechat`）

**响应示例：**
```json
{
  "login_id": "uuid-string",
  "qrcode_url": "https://.../qrcode.png",
  "qrcode_content": "...",
  "expires_at": 1234567890,
  "message": "提示信息"
}
```

**前置条件：**
- QQ 渠道：需要 NapCat QQ 服务正在运行（默认 http://localhost:3000）
- 微信渠道：需要 Wechaty SDK 已安装且有 Puppet Token
- 渠道 SDK 未就绪时，API 会返回 `500 Internal Server Error` 和明确的错误描述

---

### 5.9 查询登录状态

```
GET /channels/{channel_type}/login/status/{login_id}
```

轮询查询扫码登录状态。

**状态说明：**
- `waiting`: 等待扫码
- `scanned`: 已扫码，等待确认
- `confirmed`: 已确认登录
- `success`: 登录成功（返回用户信息）
- `expired`: 二维码已过期

**响应示例：**
```json
{
  "status": "success",
  "user_info": {
    "id": "123456",
    "nickname": "昵称",
    "avatar": "https://..."
  },
  "message": "登录成功"
}
```

---

### 5.10 获取联系人列表

```
GET /channels/{channel_type}/contacts
```

获取已登录账号的群聊和好友列表。

**响应示例：**
```json
{
  "groups": [
    {
      "id": "10001",
      "name": "技术交流群",
      "member_count": 256,
      "avatar": "https://..."
    }
  ],
  "friends": [
    {
      "id": "20001",
      "nickname": "张三",
      "remark": "产品经理",
      "avatar": "https://..."
    }
  ]
}
```

---

### 5.11 获取群成员列表

```
GET /channels/{channel_type}/groups/{group_id}/members
```

获取指定群聊的成员列表。

**响应示例：**
```json
{
  "total": 5,
  "members": [
    {
      "user_id": "10001",
      "nickname": "群主大人",
      "card": "群主",
      "role": "owner",
      "avatar": "https://...",
      "join_time": 1234567890
    }
  ]
}
```

**角色说明：**
- `owner`: 群主
- `admin`: 管理员
- `member`: 普通成员

---

### 5.12 获取支持的渠道列表

```
GET /channels/supported/list
```

获取系统支持的所有渠道类型。

---

## 6. 问答服务

### 6.1 提问

```
POST /qa/ask
```

**请求体：**
```json
{
  "agent_id": 1,
  "query": "问题内容",
  "user_id": "user_001",
  "stream": false
}
```

### 6.2 获取问答历史

```
GET /qa/history?agent_id={agent_id}
```

### 6.3 删除历史记录

```
DELETE /qa/history/{qa_id}
```

### 6.4 反馈

```
POST /qa/feedback
```

---

## 7. 系统管理

### 7.1 获取系统设置

```
GET /admin/settings
```

### 7.2 更新系统设置

```
PUT /admin/settings
```

### 7.3 模块开关

```
GET /admin/modules
```

### 7.4 仪表盘数据

```
GET /admin/dashboard
```

### 7.5 LLM 使用统计

```
GET /admin/llm-usage
```

---

## 附录 A：配置项参考

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `ZHIDA_ENABLE_FORMAT_CHECK` | `true` | 格式校验总开关 |
| `ZHIDA_FORMAT_CHECK_STRICT` | `true` | 严格模式：类型不匹配直接拒绝 |
| `ZHIDA_FORMAT_MIN_TEXT_LENGTH` | `10` | 解析后最小文本长度 |
| `ZHIDA_FORMAT_GARBAGE_THRESHOLD` | `0.5` | 乱码比例阈值 |
| `ZHIDA_FORMAT_AUTO_REJECT_EMPTY` | `true` | 空结果自动标记失败 |
| `ZHIDA_ENABLE_MINERU` | `false` | MinerU 解析开关（需安装） |
| `ZHIDA_MINERU_MODE` | `embedded` | MinerU 模式（embedded/service） |
| `ZHIDA_MINERU_FORMATS` | `pdf` | MinerU 处理的文件格式 |

## 附录 B：错误码

| HTTP 状态码 | 说明 |
|------------|------|
| 200 | 成功 |
| 400 | 请求参数错误（含格式校验拒绝） |
| 401 | 未授权 |
| 404 | 资源不存在 |
| 409 | 冲突（如知识库已挂载） |
| 429 | 请求过于频繁（限流） |
| 500 | 服务器内部错误 |
| 503 | 服务暂不可用（降级） |

**错误响应格式：**
```json
{
  "detail": "错误描述信息"
}
```

**常见格式校验错误：**
```json
{"detail": "文件类型不匹配: 扩展名声称 .pdf，实际检测为 binary"}
{"detail": "文件内容为空"}
{"detail": "不支持的文件类型: .json（未启用 MinerU 等情况）"}
{"detail": "文档质量检查未通过 (评分 0/100): 文本内容为空"}
```
