from sqlalchemy import Column, ForeignKey, Integer, UniqueConstraint
from app.core.database import Base


class AgentKnowledgeBase(Base):
    """同一知识库可被多个 Agent 挂载。"""
    __tablename__ = "agent_knowledge_bases"
    __table_args__ = (UniqueConstraint("agent_id", "knowledge_base_id", name="uq_agent_knowledge_base"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    knowledge_base_id = Column(Integer, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True)
