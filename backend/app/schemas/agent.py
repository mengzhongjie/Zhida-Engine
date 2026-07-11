"""
智答引擎（ZhiDa Engine）—— Agent Pydantic Schema

用于 API 请求/响应的数据校验和序列化。
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ============================================================
# Agent CRUD Schema
# ============================================================

class AgentCreate(BaseModel):
    """创建 Agent 请求"""
    name: str = Field(..., min_length=1, max_length=100, description="Agent 名称")
    description: Optional[str] = Field(None, description="Agent 描述")
    avatar: Optional[str] = Field(None, description="头像 URL 或 emoji")
    reply_mode: str = Field("auto", description="回复模式: auto/manual/hybrid")
    is_public: bool = Field(False, description="是否在小程序公开")


class AgentUpdate(BaseModel):
    """更新 Agent 请求"""
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="Agent 名称")
    description: Optional[str] = Field(None, description="Agent 描述")
    avatar: Optional[str] = Field(None, description="头像 URL 或 emoji")
    is_active: Optional[bool] = Field(None, description="是否启用")
    is_public: Optional[bool] = Field(None, description="是否在小程序公开")
    reply_mode: Optional[str] = Field(None, description="回复模式: auto/manual/hybrid")


class AgentOut(BaseModel):
    """Agent 输出"""
    id: int
    name: str
    description: Optional[str] = None
    avatar: Optional[str] = None
    is_active: bool
    is_public: bool = False
    status: str
    reply_mode: str
    created_at: datetime
    updated_at: datetime

    # 统计信息（非数据库字段，API 层动态填充）
    channel_count: int = Field(0, description="监听渠道数")
    today_messages: int = Field(0, description="今日消息数")
    today_answers: int = Field(0, description="今日回答数")
    success_rate: float = Field(0.0, description="响应成功率")

    model_config = {"from_attributes": True}


class AgentListOut(BaseModel):
    """Agent 列表输出"""
    total: int = Field(..., description="总数")
    items: list[AgentOut] = Field(default_factory=list, description="Agent 列表")


# ============================================================
# Agent 统计 Schema
# ============================================================

class AgentStatsOut(BaseModel):
    """Agent 统计输出"""
    agent_id: int
    agent_name: str
    status: str
    total_channels: int = 0
    active_channels: int = 0
    today_messages: int = 0
    today_answers: int = 0
    today_learned: int = 0
    success_rate: float = 0.0
    avg_response_time_ms: float = 0.0
    total_knowledge_chunks: int = 0
    last_active_at: Optional[datetime] = None
