"""
智答引擎（ZhiDa Engine）—— Agent 实例数据库模型

Agent 是系统的核心实体，每个 Agent 可以配置独立的：
- 知识库（监听哪些文档/群聊）
- LLM 模型（主模型 + 降级模型）
- 渠道（微信群/QQ 群）
- 学习策略（Q&A 提取规则）
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


class Agent(Base):
    """
    Agent 实例表 —— 每个 Agent 代表一个独立的 AI 助手

    用户可以在仪表盘管理多个 Agent，每个 Agent 配置不同的：
    - 知识来源（文档、聊天记录）
    - 监听目标（群聊、联系人）
    - 回答策略
    """

    __tablename__ = "agents"

    # 主键
    id = Column(Integer, primary_key=True, autoincrement=True)

    # 基本信息
    name = Column(String(100), nullable=False, comment="Agent 名称")
    description = Column(Text, nullable=True, comment="Agent 描述")
    avatar = Column(String(500), nullable=True, comment="头像 URL 或 emoji")

    # 状态
    is_active = Column(Boolean, default=True, comment="是否启用")
    is_public = Column(Boolean, default=False, comment="兼容旧数据的公开状态")
    status = Column(String(20), default="stopped", comment="运行状态: running/stopped/error")

    # 配置
    reply_mode = Column(String(20), default="auto", comment="回复模式: auto(自动)/manual(手动)/hybrid(混合)")

    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    # 关联关系
    llm_configs = relationship("LLMConfig", back_populates="agent", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Agent(id={self.id}, name={self.name}, status={self.status})>"
