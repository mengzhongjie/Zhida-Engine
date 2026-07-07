"""
智答引擎（ZhiDa Engine）—— 管理后台 Pydantic Schema

用于 API 请求/响应的数据校验和序列化。
"""

from typing import Optional
from pydantic import BaseModel, Field


# ============================================================
# 仪表盘统计 Schema
# ============================================================

class DashboardStatsOut(BaseModel):
    """仪表盘统计输出"""
    total_agents: int = Field(0, description="Agent 总数")
    running_agents: int = Field(0, description="运行中 Agent 数")
    total_channels: int = Field(0, description="监听渠道总数")
    active_channels: int = Field(0, description="活跃渠道数")
    today_messages: int = Field(0, description="今日消息总数")
    today_answers: int = Field(0, description="今日回答总数")
    success_rate: float = Field(0.0, description="响应成功率")
    total_knowledge_chunks: int = Field(0, description="知识库切片总数")
    total_documents: int = Field(0, description="文档总数")
    cache_hit_rate: float = Field(0.0, description="缓存命中率")


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