from sqlalchemy import Boolean, Column, Integer, String, Text

from app.core.database import Base


class WebSearchConfig(Base):
    __tablename__ = "web_search_configs"
    id = Column(Integer, primary_key=True, default=1)
    enabled = Column(Boolean, default=False, nullable=False)
    provider = Column(String(32), default="tavily", nullable=False)
    api_key = Column(Text, default="", nullable=False)
    max_results = Column(Integer, default=3, nullable=False)
