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
    total_characters: int = 0
    capacity_status: str = "normal"
    document_limit: int = 200
    size_limit_bytes: int = 120 * 1024 * 1024
    is_active: bool = True
    index_status: str = "ready"
    embedding_model: Optional[str] = None
    embedding_dimension: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class KnowledgeBaseListOut(BaseModel):
    """知识库列表输出"""
    total: int = Field(..., description="总数")
    items: list[KnowledgeBaseOut] = Field(default_factory=list, description="知识库列表")


class KnowledgeBaseBatchDeleteRequest(BaseModel):
    """批量删除知识库请求。"""
    ids: list[int] = Field(..., min_length=1, max_length=50, description="知识库 ID 列表")


class KnowledgeBaseBatchDeleteOut(BaseModel):
    deleted: list[int] = Field(default_factory=list)
    failed: list[dict] = Field(default_factory=list)


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
    character_count: int = 0
    status: str  # pending/processing/completed/error
    error_message: Optional[str] = None
    chunk_count: int = 0
    parse_time_ms: float = 0.0
    split_time_ms: float = 0.0
    embedding_time_ms: float = 0.0
    total_time_ms: float = 0.0
    processing_stage: Optional[str] = None
    failed_stage: Optional[str] = None
    processing_attempts: int = 0
    web_image_count: int = 0
    vision_image_count: int = 0
    vision_time_ms: float = 0.0
    source_url: Optional[str] = None
    source_type: str = "file"
    source_key: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    duplicate: bool = False  # 本次上传是否命中已有相同文件

    model_config = {"from_attributes": True}


class FeishuConfigOut(BaseModel):
    enabled: bool = False
    app_id: str = ""
    app_secret: str = ""
    last_test_at: Optional[datetime] = None
    last_test_success: Optional[bool] = None
    last_error: Optional[str] = None


class FeishuConfigUpdate(BaseModel):
    enabled: bool = False
    app_id: str = Field("", max_length=100)
    app_secret: Optional[str] = Field(None, max_length=500)


class FeishuImportRequest(BaseModel):
    url: str = Field(..., min_length=12, max_length=2000)
    max_nodes: int = Field(50, ge=1, le=100)


class FeishuImportStartOut(BaseModel):
    job_id: str
    status: str = "pending"


class FeishuImportJobOut(BaseModel):
    id: str
    status: str
    total: int = 0
    processed: int = 0
    imported: int = 0
    duplicate: int = 0
    error_message: Optional[str] = None
    logs: list[dict] = Field(default_factory=list)


class DocumentApproveRequest(BaseModel):
    document_ids: list[int] = Field(..., min_length=1, max_length=100)


class DocumentApproveOut(BaseModel):
    approved: int = 0
    skipped: int = 0


class DocumentBatchDeleteRequest(BaseModel):
    document_ids: list[int] = Field(..., min_length=1, max_length=100)


class DocumentBatchDeleteOut(BaseModel):
    removed: int = 0
    skipped: int = 0
    cleanup_pending: int = 0


class DocumentContentOut(BaseModel):
    id: int
    filename: str
    source_type: str
    source_url: Optional[str] = None
    content: str
    truncated: bool = False


class WebUrlImportRequest(BaseModel):
    url: str = Field(..., min_length=12, max_length=2000)


class WebUrlImportOut(BaseModel):
    document: DocumentOut
    duplicate: bool = False


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
