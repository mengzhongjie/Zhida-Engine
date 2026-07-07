"""
智答引擎（ZhiDa Engine）—— 渠道配置数据库模型

管理微信群/QQ 群等渠道的接入配置。
每个 Agent 可以监听多个渠道的聊天记录。
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship

from app.core.database import Base


class ChannelConfig(Base):
    """
    渠道配置表 —— Agent 监听的聊天渠道

    支持的渠道类型：
    - wechat: 微信群（通过 Wechaty Puppet 接入）
    - qq: QQ 群（通过 NapCat 接入）
    """

    __tablename__ = "channel_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)

    # 渠道类型
    channel_type = Column(String(20), nullable=False, comment="渠道类型: wechat/qq")

    # 渠道标识
    chat_id = Column(String(200), nullable=False, comment="群聊/联系人 ID")
    chat_name = Column(String(200), nullable=True, comment="群聊/联系人名称")

    # 监控配置
    is_listening = Column(Boolean, default=True, comment="是否正在监听")
    listen_mode = Column(String(20), default="all", comment="监听模式: all(全部)/mentioned(仅@)/questions(仅问题)")

    # 学习配置
    enable_learning = Column(Boolean, default=True, comment="是否从聊天中学习")
    target_users = Column(Text, nullable=True, comment="目标用户列表（JSON 数组，空=所有用户）")

    # 回复配置
    auto_reply = Column(Boolean, default=True, comment="是否自动回复")
    reply_with_source = Column(Boolean, default=True, comment="回复时是否附带消息来源")
    auto_mention_on_fail = Column(Boolean, default=True, comment="回答不了时是否自动 @ 指定用户")
    mention_user_ids = Column(Text, nullable=True, comment="自动 @ 的用户列表（JSON 数组）")

    # 状态
    is_active = Column(Boolean, default=True, comment="是否启用")
    last_message_at = Column(DateTime, nullable=True, comment="最后一条消息时间")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)