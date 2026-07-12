"""
智答引擎（ZhiDa Engine）—— 问答记录数据库模型

存储问答历史、用户反馈等数据，用于优化检索精度和模型效果。
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Float, ForeignKey
from sqlalchemy.orm import relationship

from app.core.database import Base


class QAHistory(Base):
    """问答历史表"""

    __tablename__ = "qa_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)

    # 问题
    question = Column(Text, nullable=False, comment="用户问题")
    normalized_question = Column(Text, nullable=True, comment="归一化后的问题（用于缓存匹配）")

    # 回答
    answer = Column(Text, nullable=True, comment="AI 回答")
    sources = Column(Text, nullable=True, comment="引用来源（JSON 格式）")

    # 性能指标
    retrieval_time_ms = Column(Float, nullable=True, comment="检索耗时（毫秒）")
    generation_time_ms = Column(Float, nullable=True, comment="生成耗时（毫秒）")
    total_time_ms = Column(Float, nullable=True, comment="总耗时（毫秒）")

    # 来源渠道
    channel = Column(String(50), nullable=True, comment="来源渠道: wechat/qq/web")
    chat_id = Column(String(200), nullable=True, comment="群聊/私聊 ID")
    user_id = Column(String(200), nullable=True, comment="提问用户 ID")

    # 用户反馈（用于优化检索精度）
    feedback = Column(String(20), nullable=True, comment="用户反馈: helpful/not_helpful/flagged")
    feedback_comment = Column(Text, nullable=True, comment="反馈备注")

    # 缓存命中
    is_cache_hit = Column(Boolean, default=False, comment="是否命中缓存")

    # Token 用量
    input_tokens = Column(Integer, default=0, comment="请求 Token 数")
    output_tokens = Column(Integer, default=0, comment="回答 Token 数")
    # 降级标记（LLM 调用失败/离线模式）
    is_degraded = Column(Boolean, default=False, comment="是否使用了降级策略")

    created_at = Column(DateTime, default=datetime.utcnow)


class QAPair(Base):
    """Q&A 对表 —— 从聊天记录中提取的问答知识"""

    __tablename__ = "qa_pairs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    knowledge_base_id = Column(Integer, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False)

    question = Column(Text, nullable=False, comment="问题")
    answer = Column(Text, nullable=False, comment="回答")

    # 来源信息
    source_type = Column(String(20), default="chat", comment="来源类型: chat/document/manual")
    source_chat_id = Column(String(200), nullable=True, comment="来源群聊 ID")
    source_user_id = Column(String(200), nullable=True, comment="来源用户 ID")
    source_message_id = Column(String(200), nullable=True, comment="来源消息 ID")

    # 质量评分
    quality_score = Column(Float, default=0.0, comment="质量评分（0-1）")
    use_count = Column(Integer, default=0, comment="被引用次数")

    # 向量化
    is_vectorized = Column(Boolean, default=False, comment="是否已向量化")

    created_at = Column(DateTime, default=datetime.utcnow)