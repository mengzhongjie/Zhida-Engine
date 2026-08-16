"""
智答引擎（ZhiDa Engine）—— 问答 Pydantic Schema

用于 API 请求/响应的数据校验和序列化。
"""

from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field


# ============================================================
# 问答请求/响应 Schema
# ============================================================

class QAAskRequest(BaseModel):
    """提问请求"""
    agent_id: int = Field(..., description="Agent ID")
    question: str = Field(..., min_length=1, max_length=2000, description="问题内容")
    chat_id: Optional[str] = Field(None, description="聊天 ID（群聊/私聊）")
    chat_type: Optional[str] = Field(None, description="聊天类型: private/group")
    user_id: Optional[str] = Field(None, description="提问用户 ID")
    stream: bool = Field(False, description="是否流式输出")
    response_detail: Literal["concise", "detailed"] = Field("concise", description="本轮回答详略")


class QASource(BaseModel):
    """回答来源"""
    document_name: str = Field(..., description="文档名称")
    chunk_text: str = Field(..., description="相关文本片段")
    score: float = Field(..., description="相关度评分")
    source_type: str = Field("document", description="来源类型: document/chat_learned")


class QAAnswerOut(BaseModel):
    """问答回答输出"""
    question: str
    answer: str
    sources: list[QASource] = Field(default_factory=list, description="回答来源")
    confidence: float = Field(0.0, description="置信度")
    response_time_ms: float = Field(0.0, description="响应时间（毫秒）")
    model_used: str = Field("", description="使用的模型")
    from_cache: bool = Field(False, description="是否来自缓存")


# ============================================================
# 问答历史 Schema
# ============================================================

class QAHistoryOut(BaseModel):
    """问答历史输出"""
    id: int
    agent_id: int
    question: str
    answer: str
    sources: Optional[str] = None  # JSON 字符串
    confidence: float = 0.0
    response_time_ms: float = 0.0
    model_used: str = ""
    from_cache: bool = False
    chat_id: Optional[str] = None
    chat_type: Optional[str] = None
    user_id: Optional[str] = None
    channel: Optional[str] = None  # web/qq/feishu
    input_tokens: int = 0
    output_tokens: int = 0
    is_degraded: bool = False
    web_search_count: int = 0
    feedback: Optional[str] = None  # useful/useless/none
    created_at: datetime

    model_config = {"from_attributes": True}


class QAHistoryListOut(BaseModel):
    """问答历史列表输出"""
    total: int = Field(..., description="总数")
    items: list[QAHistoryOut] = Field(default_factory=list, description="历史列表")


# ============================================================
# 用户反馈 Schema
# ============================================================

class QAFeedbackRequest(BaseModel):
    """用户反馈请求"""
    qa_id: int = Field(..., description="问答记录 ID")
    feedback: str = Field(..., description="反馈: useful/useless")
    comment: Optional[str] = Field(None, max_length=500, description="反馈备注")
