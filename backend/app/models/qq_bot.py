"""QQ 官方机器人配置与群绑定。密钥仅加密存储。"""
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from app.core.database import Base

class QQBotConfig(Base):
    __tablename__ = "qq_bot_configs"
    id = Column(Integer, primary_key=True, default=1)
    enabled = Column(Boolean, nullable=False, default=False)
    app_id = Column(String(100), nullable=False, default="")
    app_secret = Column(Text, nullable=False, default="")
    response_detail = Column(String(20), nullable=False, default="concise")
    p2p_enabled = Column(Boolean, nullable=False, default=False)
    p2p_access_mode = Column(String(20), nullable=False, default="all")
    p2p_agent_id = Column(Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True)
    p2p_allow_openids = Column(Text, nullable=False, default="")
    last_test_success = Column(Boolean, nullable=True)
    last_error = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

class QQBotGroupBinding(Base):
    __tablename__ = "qq_bot_group_bindings"
    id = Column(Integer, primary_key=True, autoincrement=True)
    group_openid = Column(String(128), nullable=False, unique=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
