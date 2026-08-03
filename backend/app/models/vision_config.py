"""视觉模型配置：用于网页图片、图表和截图的理解。"""

from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from app.core.database import Base


class VisionConfig(Base):
    __tablename__ = "vision_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), default="视觉模型", nullable=False)
    is_primary = Column(Boolean, default=False, nullable=False)
    is_fallback = Column(Boolean, default=False, nullable=False)
    enabled = Column(Boolean, default=False, nullable=False)
    base_url = Column(String(500), default="", nullable=False)
    model_name = Column(String(200), default="", nullable=False)
    api_key = Column(Text, default="", nullable=False)
    last_test_at = Column(DateTime, nullable=True)
    last_test_success = Column(Boolean, nullable=True)
    last_error = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
