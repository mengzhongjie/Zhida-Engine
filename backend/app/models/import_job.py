"""外部数据源导入任务，轻量持久化进度以支持管理台轮询。"""

from datetime import datetime
from sqlalchemy import Column, DateTime, Integer, String, Text

from app.core.database import Base


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id = Column(String(36), primary_key=True)
    knowledge_base_id = Column(Integer, nullable=False, index=True)
    source_type = Column(String(40), nullable=False)
    source_url = Column(String(2000), nullable=False)
    max_nodes = Column(Integer, nullable=False, default=50)
    status = Column(String(20), nullable=False, default="pending")  # pending/processing/completed/failed
    total = Column(Integer, nullable=False, default=0)
    processed = Column(Integer, nullable=False, default=0)
    imported = Column(Integer, nullable=False, default=0)
    duplicate = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    logs_json = Column(Text, nullable=False, default="[]")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
