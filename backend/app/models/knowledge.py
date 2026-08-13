"""
智答引擎（ZhiDa Engine）—— 知识库数据库模型

管理知识库、文档、文本切片等实体。
知识来源包括：上传文档（PDF/Excel/Word）和聊天记录（Q&A 对）。
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, Float, ForeignKey, Boolean, Enum as SAEnum, UniqueConstraint
from sqlalchemy.orm import relationship

from app.core.database import Base


class KnowledgeBase(Base):
    """知识库表 —— 每个 Agent 可关联多个知识库，也支持独立知识库

    知识库可以独立创建和管理，Agent 创建时可选择挂载已有的知识库。
    独立知识库 agent_id 为 NULL，不归属于任何 Agent。
    """

    __tablename__ = "knowledge_bases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, comment="所属 Agent ID（可空，表示独立知识库）")
    name = Column(String(200), nullable=False, comment="知识库名称")
    description = Column(Text, nullable=True, comment="知识库描述")
    is_active = Column(Boolean, default=True, comment="是否启用")

    # 统计
    document_count = Column(Integer, default=0, comment="文档数量")
    chunk_count = Column(Integer, default=0, comment="子切片数量（用于索引）")
    parent_chunk_count = Column(Integer, default=0, comment="父块数量")
    total_size_bytes = Column(Integer, default=0, comment="总大小（字节）")
    total_characters = Column(Integer, default=0, comment="资料正文总字符数")
    qa_pair_count = Column(Integer, default=0, comment="Q&A 对数量")
    capacity_status = Column(String(20), default="normal", nullable=False, comment="容量状态: normal/near_limit/full")

    # 索引指纹：避免不同嵌入模型/维度/距离空间的向量被混用。
    embedding_model = Column(String(300), nullable=True)
    embedding_dimension = Column(Integer, nullable=True)
    index_space = Column(String(20), nullable=True)
    index_version = Column(String(40), nullable=True)
    index_status = Column(String(30), default="ready", nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")


class Document(Base):
    """文档表 —— 上传到知识库的文档"""

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("knowledge_base_id", "content_hash", name="uq_documents_kb_content_hash"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    knowledge_base_id = Column(Integer, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String(500), nullable=False, comment="原始文件名")
    file_type = Column(String(20), nullable=False, comment="文件类型: pdf/docx/xlsx/txt/md")
    file_path = Column(String(1000), nullable=False, comment="文件存储路径")
    source_url = Column(String(1500), nullable=True, comment="外部数据源原始链接")
    source_type = Column(String(30), nullable=False, default="file", comment="来源类型: file/web_page/cloud_document")
    source_key = Column(String(500), nullable=True, index=True, comment="数据源稳定身份，如飞书 docx token")
    file_size = Column(Integer, default=0, comment="文件大小（字节）")
    character_count = Column(Integer, default=0, comment="解析/保存后的正文字符数")
    content_hash = Column(String(64), nullable=True, index=True, comment="文件 SHA-256，用于同知识库去重")

    # 处理状态
    status = Column(String(20), default="pending", comment="处理状态: pending/processing/completed/failed")
    error_message = Column(Text, nullable=True, comment="错误信息")

    # 统计
    chunk_count = Column(Integer, default=0, comment="子切片数量（用于索引）")
    parent_chunk_count = Column(Integer, default=0, comment="父块数量")
    parse_time_ms = Column(Float, default=0.0, comment="解析耗时（毫秒）")
    split_time_ms = Column(Float, default=0.0, comment="切分耗时（毫秒）")
    embedding_time_ms = Column(Float, default=0.0, comment="向量化及写入耗时（毫秒）")
    total_time_ms = Column(Float, default=0.0, comment="处理总耗时（毫秒）")
    processing_stage = Column(String(30), nullable=True, comment="当前或失败阶段")
    failed_stage = Column(String(30), nullable=True, comment="失败阶段")
    processing_attempts = Column(Integer, default=0, comment="已处理次数")
    web_image_count = Column(Integer, default=0, comment="网页正文发现的图片数")
    vision_image_count = Column(Integer, default=0, comment="视觉模型成功识别的图片数")
    vision_time_ms = Column(Float, default=0.0, comment="网页视觉识别总耗时（毫秒）")

    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")


class DocumentChunk(Base):
    """文档父块表 —— 存储父子块切分中的父块内容

    父子块切分策略：
    - 子块（Child）: 200字符，重叠50字符 → 向量化后存入 ChromaDB 用于检索
    - 父块（Parent）: 800字符（子块4倍） → 存入此表，通过子块的 parent_id 关联
    - 检索时：找到子块 → 通过 parent_id 找到父块 → 返回父块作为完整上下文
    """

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "parent_id", name="uq_document_chunks_document_parent"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    knowledge_base_id = Column(Integer, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True)

    # 父块标识（与 ChromaDB 中子块 metadata 中的 parent_id 对应）
    parent_id = Column(String(100), nullable=False, index=True, comment="父块唯一标识")

    # 内容
    content = Column(Text, nullable=False, comment="父块文本内容")
    content_type = Column(String(20), default="text", comment="内容类型: text/code")
    code_lang = Column(String(50), nullable=True, comment="代码语言（content_type=code 时）")

    # 位置信息
    chunk_index = Column(Integer, default=0, comment="父块在文档中的索引")
    child_start_index = Column(Integer, default=0, comment="对应的第一个子块索引")
    child_end_index = Column(Integer, default=0, comment="对应的最后一个子块索引")

    # 元数据（JSON 字符串）
    metadata_json = Column(Text, nullable=True, comment="元数据 JSON")

    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
