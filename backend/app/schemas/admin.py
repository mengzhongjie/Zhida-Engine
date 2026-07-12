"""
智答引擎（ZhiDa Engine）—— 管理后台 Pydantic Schema

用于 API 请求/响应的数据校验和序列化。
"""

from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict


# ============================================================
# 仪表盘统计 Schema
# ============================================================

class DashboardStatsOut(BaseModel):
    """仪表盘统计输出"""
    total_agents: int = Field(0, description="Agent 总数")
    running_agents: int = Field(0, description="运行中 Agent 数")
    today_messages: int = Field(0, description="今日消息总数")
    today_answers: int = Field(0, description="今日回答总数")
    success_rate: float = Field(0.0, description="响应成功率（非降级回答占比）")
    total_knowledge_chunks: int = Field(0, description="知识库切片总数")
    total_documents: int = Field(0, description="文档总数")
    cache_hit_rate: float = Field(0.0, description="缓存命中率")
    today_input_tokens: int = Field(0, description="今日请求 Token 数")
    today_output_tokens: int = Field(0, description="今日回答 Token 数")
    web_search_count: int = Field(0, description="网络检索次数")


class WebSearchConfigOut(BaseModel):
    enabled: bool = False
    provider: str = "tavily"
    api_key: str = ""
    max_results: int = 3


class WebSearchConfigUpdate(BaseModel):
    enabled: bool
    provider: str = "tavily"
    api_key: Optional[str] = None
    max_results: int = Field(3, ge=1, le=10)


# ============================================================
# 模块开关 Schema
# ============================================================

class ModuleSwitchesOut(BaseModel):
    """模块开关输出"""
    enable_single_flight: bool = Field(..., description="Single-Flight 幂等合并")
    enable_graph_retrieval: bool = Field(..., description="图检索增强")
    enable_rerank: bool = Field(..., description="重排序")
    enable_streaming: bool = Field(..., description="流式输出")
    enable_auto_learning: bool = Field(..., description="自动学习群聊知识")
    enable_source_citation: bool = Field(..., description="回答后附带消息来源")
    enable_auto_mention: bool = Field(..., description="回答不了时自动 @ 指定用户")
    enable_rate_limit: bool = Field(..., description="限流总开关")
    enable_local_only: bool = Field(..., description="仅允许本地请求")


class ModuleSwitchesUpdate(BaseModel):
    """模块开关更新请求"""
    enable_single_flight: Optional[bool] = Field(None, description="Single-Flight 幂等合并")
    enable_graph_retrieval: Optional[bool] = Field(None, description="图检索增强")
    enable_rerank: Optional[bool] = Field(None, description="重排序")
    enable_streaming: Optional[bool] = Field(None, description="流式输出")
    enable_auto_learning: Optional[bool] = Field(None, description="自动学习群聊知识")
    enable_source_citation: Optional[bool] = Field(None, description="回答后附带消息来源")
    enable_auto_mention: Optional[bool] = Field(None, description="回答不了时自动 @ 指定用户")
    enable_rate_limit: Optional[bool] = Field(None, description="限流总开关")


# ============================================================
# 缓存统计 Schema
# ============================================================

class CacheStatsOut(BaseModel):
    """缓存统计输出"""
    hits: int = Field(0, description="命中次数")
    misses: int = Field(0, description="未命中次数")
    total: int = Field(0, description="总请求数")
    hit_rate: float = Field(0.0, description="命中率")
    memory_entries: int = Field(0, description="内存缓存条目数")
    disk_entries: int = Field(0, description="磁盘缓存条目数")


# ============================================================
# 限流配置 Schema
# ============================================================

class RateLimitConfigOut(BaseModel):
    """限流配置输出"""
    token_bucket_rate: float = Field(10.0, description="令牌桶速率（令牌/秒）")
    token_bucket_capacity: int = Field(3, description="令牌桶容量")
    window_size_seconds: int = Field(60, description="滑动窗口大小（秒）")
    window_max_requests: int = Field(5, description="窗口内最大请求数")
    question_cooldown_seconds: int = Field(300, description="问题冷却时间（秒）")
    silent_period_enabled: bool = Field(True, description="是否启用静默时段")
    private_chat_relaxed: bool = Field(True, description="私聊是否放宽限制")


class RateLimitConfigUpdate(BaseModel):
    """限流配置更新请求"""
    token_bucket_rate: Optional[float] = Field(None, description="令牌桶速率")
    token_bucket_capacity: Optional[int] = Field(None, description="令牌桶容量")
    window_size_seconds: Optional[int] = Field(None, description="滑动窗口大小")
    window_max_requests: Optional[int] = Field(None, description="窗口内最大请求数")
    question_cooldown_seconds: Optional[int] = Field(None, description="问题冷却时间")
    silent_period_enabled: Optional[bool] = Field(None, description="是否启用静默时段")
    private_chat_relaxed: Optional[bool] = Field(None, description="私聊是否放宽限制")


# ============================================================
# LLM 使用统计 Schema（仪表盘监控用）
# ============================================================

class LLMUsageStatsOut(BaseModel):
    """LLM 使用统计输出"""
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="LLM 配置 ID")
    provider_name: str = Field(..., description="厂商名称")
    model_name: str = Field(..., description="模型名称")
    is_primary: bool = Field(False, description="是否主模型")
    is_active: bool = Field(True, description="是否启用")
    tokens_used_today: int = Field(0, description="今日已使用 Token 数")
    max_tokens_per_day: int = Field(1000000, description="每日 Token 限额")
    requests_today: int = Field(0, description="今日请求数")
    max_requests_per_minute: int = Field(30, description="每分钟请求限额")
    max_tokens_per_request: int = Field(4096, description="单次请求 Token 限额")
    last_test_success: Optional[bool] = Field(None, description="最近连接测试结果")
    last_test_at: Optional[datetime] = Field(None, description="最近连接测试时间")


# ============================================================
# 记忆层 Schema
# ============================================================

class MemoryItemOut(BaseModel):
    """记忆条目输出"""
    id: str = Field(..., description="记忆 ID")
    memory: str = Field(..., description="记忆内容")
    user_id: Optional[str] = Field(None, description="用户 ID")
    agent_id: Optional[str] = Field(None, description="Agent ID")
    run_id: Optional[str] = Field(None, description="运行 ID")
    metadata: Optional[dict] = Field(None, description="元数据")
    score: Optional[float] = Field(None, description="匹配得分（搜索时返回）")
    created_at: Optional[datetime] = Field(None, description="创建时间")
    updated_at: Optional[datetime] = Field(None, description="更新时间")


class MemorySearchIn(BaseModel):
    """记忆搜索请求"""
    query: str = Field(..., description="搜索查询")
    user_id: Optional[str] = Field(None, description="用户 ID 过滤")
    agent_id: Optional[str] = Field(None, description="Agent ID 过滤")
    run_id: Optional[str] = Field(None, description="运行 ID 过滤")
    limit: int = Field(20, ge=1, le=100, description="返回数量")
    rerank: bool = Field(False, description="是否重排序")


class MemoryAddIn(BaseModel):
    """添加记忆请求"""
    content: str = Field(..., description="记忆内容")
    user_id: Optional[str] = Field(None, description="用户 ID")
    agent_id: Optional[str] = Field(None, description="Agent ID")
    run_id: Optional[str] = Field(None, description="运行 ID")
    metadata: Optional[dict] = Field(None, description="元数据")


class MemoryUpdateIn(BaseModel):
    """更新记忆请求"""
    content: str = Field(..., description="新的记忆内容")


class MemoryStatsOut(BaseModel):
    """记忆统计输出"""
    is_available: bool = Field(False, description="记忆层是否可用")
    total_count: int = Field(0, description="记忆总数")
