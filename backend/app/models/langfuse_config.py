from sqlalchemy import Boolean, Column, Integer, String, Text
from app.core.database import Base


class LangfuseConfig(Base):
    __tablename__ = "langfuse_configs"
    id = Column(Integer, primary_key=True, default=1)
    enabled = Column(Boolean, default=False, nullable=False)
    host = Column(String(500), default="https://cloud.langfuse.com", nullable=False)
    public_key = Column(Text, default="", nullable=False)
    secret_key = Column(Text, default="", nullable=False)
    evaluator_enabled = Column(Boolean, default=False, nullable=False)
    evaluator_model_config_id = Column(Integer, nullable=True)
