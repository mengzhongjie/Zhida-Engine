"""
智答引擎（ZhiDa Engine）—— 知识库数据库模型

管理知识库、文档、文本切片等实体。
知识来源包括：上传文档（PDF/Excel/Word）和聊天记录（Q&A 对）。
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, Float, ForeignKey, Enum as SAEnum
from sqlalchemy.orm import relationship

from app.core.database import Base


class KnowledgeBase(Base):
    """知识库表 —— 每个 Agent 可关联多个知识库"""

    __tablename__ = "knowledge_bases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(200), nullable=False, comment="知识库名称")
    description = Column(Text, nullable=True, comment="知识库描述")

    # 统计
    document_count = Column(Integer, default=0, comment="文档数量")
    chunk_count = Column(Integer, default=0, comment="切片数量")
    qa_pair_count = Column(Integer, default=0, comment="Q&A 对数量")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Document(Base):
    """文档表 —— 上传到知识库的文档"""

    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    knowledge_base_id = Column(Integer, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String(500), nullable=False, comment="原始文件名")
    file_type = Column(String(20), nullable=False, comment="文件类型: pdf/docx/xlsx/txt/md")
    file_path = Column(String(1000), nullable=False, comment="文件存储路径")
    file_size = Column(Integer, default=0, comment="文件大小（字节）")

    # 处理状态
    status = Column(String(20), default="pending", comment="处理状态: pending/processing/completed/failed")
    error_message = Column(Text, nullable=True, comment="错误信息")

    # 统计
    chunk_count = Column(Integer, default=0, comment="切片数量")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)