"""飞书应用身份配置（凭据仅保存在本机加密 SQLite 中）。"""

from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from app.core.database import Base


class FeishuConfig(Base):
    __tablename__ = "feishu_configs"

    id = Column(Integer, primary_key=True, default=1)
    enabled = Column(Boolean, default=False, nullable=False)
    app_id = Column(String(100), default="", nullable=False)
    app_secret = Column(Text, default="", nullable=False)
    last_test_at = Column(DateTime, nullable=True)
    last_test_success = Column(Boolean, nullable=True)
    last_error = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
