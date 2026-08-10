"""持久化的 Agent 可观测配置。"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from app.core.database import Base


class ObservabilityConfig(Base):
    __tablename__ = "observability_configs"

    # 单用户部署只有一套 Langfuse 配置，固定使用 id=1。
    id = Column(Integer, primary_key=True, default=1)
    langfuse_enabled = Column(Boolean, default=False, nullable=False)
    langfuse_host = Column(String(500), default="https://cloud.langfuse.com", nullable=False)
    langfuse_public_key = Column(Text, default="", nullable=False)
    langfuse_secret_key = Column(Text, default="", nullable=False)
    # 开启后才向 answer Generation 提供问题与检索证据，供 Langfuse 云端 Judge 评分。
    online_evaluation_enabled = Column(Boolean, default=False, nullable=False)
    last_test_success = Column(Boolean, nullable=True)
    last_test_at = Column(DateTime, nullable=True)
    last_test_message = Column(String(500), nullable=True)
