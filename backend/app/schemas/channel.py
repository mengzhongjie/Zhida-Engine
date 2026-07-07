"""
智答引擎（ZhiDa Engine）—— 渠道配置 Pydantic Schema

用于 API 请求/响应的数据校验和序列化。
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ============================================================
# 渠道配置 CRUD Schema
# ============================================================

class ChannelConfigCreate(BaseModel):
    """创建渠道配置请求"""
    agent_id: int = Field(..., description="所属 Agent ID")
    channel_type: str = Field(..., description="渠道类型: wechat/qq")
    chat_id: str = Field(..., min_length=1, max_length=200, description="群聊/联系人 ID")
    chat_name: Optional[str] = Field(None, max_length=200, description="群聊/联系人名称")
    listen_mode: str = Field("all", description="监听模式: all/mentioned/questions")
    enable_learning: bool = Field(True, description="是否从聊天中学习")
    target_users: Optional[str] = Field(None, description="目标用户列表（JSON 数组）")
    auto_reply: bool = Field(True, description="是否自动回复")
    reply_with_source: bool = Field(True, description="回复时是否附带消息来源")
    auto_mention_on_fail: bool = Field(True, description="回答不了时是否自动 @ 指定用户")
    mention_user_ids: Optional[str] = Field(None, description="自动 @ 的用户列表（JSON 数组）")


class ChannelConfigUpdate(BaseModel):
    """更新渠道配置请求"""
    chat_name: Optional[str] = Field(None, max_length=200, description="群聊/联系人名称")
    is_listening: Optional[bool] = Field(None, description="是否正在监听")
    listen_mode: Optional[str] = Field(None, description="监听模式: all/mentioned/questions")
    enable_learning: Optional[bool] = Field(None, description="是否从聊天中学习")
    target_users: Optional[str] = Field(None, description="目标用户列表（JSON 数组）")
    auto_reply: Optional[bool] = Field(None, description="是否自动回复")
    reply_with_source: Optional[bool] = Field(None, description="回复时是否附带消息来源")
    auto_mention_on_fail: Optional[bool] = Field(None, description="回答不了时是否自动 @ 指定用户")
    mention_user_ids: Optional[str] = Field(None, description="自动 @ 的用户列表（JSON 数组）")
    is_active: Optional[bool] = Field(None, description="是否启用")


class ChannelConfigOut(BaseModel):
    """渠道配置输出"""
    id: int
    agent_id: int
    channel_type: str
    chat_id: str
    chat_name: Optional[str] = None
    is_listening: bool
    listen_mode: str
    enable_learning: bool
    target_users: Optional[str] = None
    auto_reply: bool
    reply_with_source: bool
    auto_mention_on_fail: bool
    mention_user_ids: Optional[str] = None
    is_active: bool
    last_message_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    # 统计信息（非数据库字段）
    today_messages: int = Field(0, description="今日消息数")
    today_answers: int = Field(0, description="今日回答数")

    model_config = {"from_attributes": True}


class ChannelConfigListOut(BaseModel):
    """渠道配置列表输出"""
    total: int = Field(..., description="总数")
    items: list[ChannelConfigOut] = Field(default_factory=list, description="渠道列表")


# ============================================================
# 渠道统计 Schema
# ============================================================

class ChannelStatsOut(BaseModel):
    """渠道统计输出"""
    channel_id: int
    chat_name: str
    channel_type: str
    is_listening: bool
    today_messages: int = 0
    today_answers: int = 0
    today_learned: int = 0
    last_message_at: Optional[datetime] = None