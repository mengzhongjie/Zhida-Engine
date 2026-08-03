from sqlalchemy import Boolean, Column, Integer, String, Text

from app.core.database import Base


class WebSearchConfig(Base):
    __tablename__ = "web_search_configs"
    id = Column(Integer, primary_key=True, default=1)
    enabled = Column(Boolean, default=False, nullable=False)
    provider = Column(String(32), default="tavily", nullable=False)
    # 按供应商独立保存，避免切换搜索源时误用另一家的 API Key。
    tavily_api_key = Column(Text, default="", nullable=False)
    exa_api_key = Column(Text, default="", nullable=False)
    # 兼容旧版本的单一密钥列，迁移完成后不再用于新配置。
    api_key = Column(Text, default="", nullable=False)
    max_results = Column(Integer, default=3, nullable=False)
