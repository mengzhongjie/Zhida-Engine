# 重构实现方案文档 + LLM 配置厂商模板 Spec

## Why

当前实现方案文档（智答引擎实现方案.md）经过多轮迭代，结构已不清晰，需要重构为条理分明的最终版本文档。同时 LLM 配置需要从简单的模型列表扩展为支持厂商模板自动填充 + 全自定义双模式。

## What Changes

### 文档重构
- 重新组织文档结构，按模块独立成章，清晰分层
- 移除冗余的迭代讨论痕迹，保留最终决策
- 统一章节编号，确保目录可导航
- 将 UI 设计、部署方案、降级策略等分散内容归入正确的章节

### LLM 配置厂商模板
- 新增厂商模板系统：选择厂商后自动填充 base_url、模型列表等字段
- 用户只需手动填入 API Key 即可完成配置
- 同时保留全自定义模式：所有字段均可手动输入
- 内置常见厂商模板（DeepSeek、阿里云、OpenAI、Anthropic、Ollama 本地等）

## Impact

- Affected specs: 无（新项目）
- Affected code: `智答引擎实现方案.md`（文档重构），LLM 网关配置相关设计（新增）

## ADDED Requirements

### Requirement: 文档结构标准化
方案文档 SHALL 按以下结构组织：

```
一、项目概述（背景、目标用户、价值主张）
二、技术栈（含选型理由对比）
三、系统架构（整体架构图 + 目录结构）
四、核心模块设计
  4.1 知识库模块（文档解析、切片、向量化、聊天学习、精度优化）
  4.2 问答引擎（混合检索、图检索、Prompt、LLM网关、流式输出）
  4.3 群聊渠道接入（微信/QQ 机器人、统一消息协议、群聊功能）
  4.4 缓存与降级（缓存策略、Single-Flight、模块开关、降级策略）
  4.5 限流与安全（刷屏限流、数据安全、本地部署）
  4.6 UI 界面设计（仪表盘、Agent 详情、实时消息）
  4.7 数据库设计
五、实施路线图（分阶段、里程碑）
六、部署方案（PyInstaller 打包、NSIS 安装包、启动流程）
七、关键设计决策（决策表）
八、风险与缓解
九、验证方式
```

#### Scenario: 读者按目录导航
- **WHEN** 读者打开文档
- **THEN** 每个章节有清晰的标题层级，可从目录直接跳转

### Requirement: LLM 厂商模板自动填充
系统 SHALL 在 LLM 配置页提供厂商模板选择功能，用户选择厂商后自动填充部分字段。

#### Scenario: 选择内置厂商模板
- **WHEN** 用户在设置页选择"DeepSeek"厂商
- **THEN** 系统自动填充：
  - 厂商名称：DeepSeek
  - Base URL：`https://api.deepseek.com/v1`
  - 可用模型列表：`deepseek-chat`、`deepseek-reasoner`
  - 默认模型：`deepseek-chat`
  - API Key 输入框：留空，等待用户手动填入

#### Scenario: 选择本地 Ollama
- **WHEN** 用户在设置页选择"Ollama（本地）"
- **THEN** 系统自动填充：
  - 厂商名称：Ollama
  - Base URL：`http://localhost:11434/v1`
  - API Key：自动填入 `ollama`（无需真实 key）
  - 提示用户确保 Ollama 已安装并运行

#### Scenario: 全自定义配置
- **WHEN** 用户选择"自定义"厂商
- **THEN** 所有字段（厂商名称、Base URL、模型名称、API Key）均为空白手动输入框
- **AND** 不提供预设模型列表，用户自行输入模型名称

### Requirement: 内置厂商模板列表
系统 SHALL 预置以下厂商模板：

| 厂商 | Base URL | 默认模型 | 需要 API Key |
|------|----------|---------|-------------|
| DeepSeek | `https://api.deepseek.com/v1` | deepseek-v4-pro | 是 |
| 阿里云百炼 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | qwen3.7-max | 是 |
| OpenAI | `https://api.openai.com/v1` | gpt-5.5 | 是 |
| Anthropic | `https://api.anthropic.com/v1` | claude-opus-4.8 | 是 |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | glm-5.2 | 是 |
| 月之暗面 | `https://api.moonshot.cn/v1` | kimi-k2.7 | 是 |
| 字节豆包 | `https://ark.cn-beijing.volces.com/api/v3` | doubao-seed-2-pro | 是 |
| Ollama（本地） | `http://localhost:11434/v1` | qwen3:14b | 否 |
| 自定义 | 用户自行填写 | 用户自行填写 | 用户决定 |

#### Scenario: 厂商列表展示
- **WHEN** 用户打开 LLM 设置页
- **THEN** 看到厂商选择下拉框，列出所有内置厂商 + "自定义"
- **AND** 云端厂商和本地厂商分组显示，带图标区分

### Requirement: 多模型配置支持
系统 SHALL 支持同时配置多个 LLM 模型，用于主模型和降级模型。

#### Scenario: 配置主模型和降级模型
- **WHEN** 用户在设置页配置 LLM
- **THEN** 可以配置：
  - 主模型：选择厂商 → 自动填充 → 输入 API Key
  - 降级模型：选择另一个厂商（或本地 Ollama）→ 自动填充
  - 降级策略：主模型不可用时自动切换到降级模型

## MODIFIED Requirements

### Requirement: LLM 网关配置（原方案 4.2.4）
原方案中的 `LLMGateway` 硬编码模型列表 SHALL 改为从数据库/user 配置中读取，支持厂商模板和自定义模型混合。

#### Scenario: 从配置读取模型列表
- **WHEN** LLM 网关初始化
- **THEN** 从 SQLite 配置表读取用户已配置的模型列表
- **AND** 不再使用硬编码的 `BUILTIN_MODELS` 字典

## REMOVED Requirements

无。