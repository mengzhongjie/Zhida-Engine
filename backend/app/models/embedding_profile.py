"""可保存的向量模型配置；只有主配置会真正参与向量化。"""
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from app.core.database import Base

class EmbeddingProfile(Base):
    __tablename__ = "embedding_profiles"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    provider_id = Column(String(50), nullable=False, default="custom")
    provider_name = Column(String(100), nullable=False, default="自定义")
    mode = Column(String(20), nullable=False, default="local")
    local_model = Column(String(200), default="BAAI/bge-large-zh-v1.5")
    local_device = Column(String(20), default="cpu")
    cloud_base_url = Column(String(500), default="")
    cloud_api_key = Column(Text, default="")
    cloud_model = Column(String(200), default="")
    cloud_dimension = Column(Integer, default=1536)
    is_primary = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    last_test_success = Column(Boolean, nullable=True)
    last_test_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
