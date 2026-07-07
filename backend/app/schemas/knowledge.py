"""
智答引擎（ZhiDa Engine）—— 知识库 Pydantic Schema

用于 API 请求/响应的数据校验和序列化。
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ============================================================
# 知识库 Schema
# ============================================================

class KnowledgeBaseCreate(BaseModel):
    """创建知识库请求"""
    agent_id: Optional[int] = Field(None, description="所属 Agent ID（可空，表示独立知识库）")
    name: str = Field(..., min_length=1, max_length=200, description="知识库名称")
    description: Optional[str] = Field(None, description="知识库描述")


class KnowledgeBaseUpdate(BaseModel):
    """更新知识库请求"""
    name: Optional[str] = Field(None, min_length=1, max_length=200, description="知识库名称")
    description: Optional[str] = Field(None, description="知识库描述")
    is_active: Optional[bool] = Field(None, description="是否启用")


class KnowledgeBaseOut(BaseModel):
    """知识库输出"""
    id: int
    agent_id: Optional[int] = None
    name: str
    description: Optional[str] = None
    document_count: int = 0
    chunk_count: int = 0
    total_size_bytes: int = 0
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class KnowledgeBaseListOut(BaseModel):
    """知识库列表输出"""
    total: int = Field(..., description="总数")
    items: list[KnowledgeBaseOut] = Field(default_factory=list, description="知识库列表")


# ============================================================
# 文档 Schema
# ============================================================

class DocumentOut(BaseModel):
    """文档输出"""
    id: int
    knowledge_base_id: int
    filename: str
    file_type: str
    file_size: int
    status: str  # pending/processing/completed/error
    error_message: Optional[str] = None
    chunk_count: int = 0
    parse_time_ms: float = 0.0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentListOut(BaseModel):
    """文档列表输出"""
    total: int = Field(..., description="总数")
    items: list[DocumentOut] = Field(default_factory=list, description="文档列表")


# ============================================================
# 知识库统计 Schema
# ============================================================

class KnowledgeStatsOut(BaseModel):
    """知识库统计输出"""
    total_documents: int = 0
    total_chunks: int = 0
    total_size_mb: float = 0.0
    documents_by_type: dict[str, int] = Field(default_factory=dict)
    documents_by_status: dict[str, int] = Field(default_factory=dict)
    last_upload_at: Optional[datetime] = None


# ============================================================
# 知识库优化 Schema
# ============================================================

class OptimizeRequest(BaseModel):
    """知识库优化请求"""
    agent_id: int = Field(..., description="Agent ID")
    remove_duplicates: bool = Field(True, description="是否去除重复切片")
    merge_small_chunks: bool = Field(True, description="是否合并小切片")


class OptimizeResponse(BaseModel):
    """知识库优化响应"""
    success: bool
    message: str
    chunks_before: int = 0
    chunks_after: int = 0
    removed_count: int = 0