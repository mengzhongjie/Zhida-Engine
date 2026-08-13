"""知识库黄金集与 Agent 评测运行记录。"""
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from app.core.database import Base


class EvaluationCase(Base):
    __tablename__ = "evaluation_cases"
    id = Column(Integer, primary_key=True, autoincrement=True)
    knowledge_base_id = Column(Integer, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True)
    question = Column(Text, nullable=False)
    reference_answer = Column(Text, nullable=True)
    expected_document_ids_json = Column(Text, nullable=False, default="[]")
    required_facts_json = Column(Text, nullable=False, default="[]")
    is_enabled = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    # 管理端展示名称；与 Langfuse 的 run_name 分离，避免修改本地名称影响云端既有实验。
    experiment_name = Column(String(120), nullable=True)
    # 本次检索评测与 RAG 调用共同使用的 K，保证 NDCG/Recall 与实际候选集一致。
    retrieval_top_k = Column(Integer, nullable=False, default=4)
    status = Column(String(20), nullable=False, default="pending")
    case_count = Column(Integer, nullable=False, default=0)
    completed_count = Column(Integer, nullable=False, default=0)
    retrieval_score = Column(Float, nullable=True)
    fact_score = Column(Float, nullable=True)
    faithfulness_score = Column(Float, nullable=True)
    answer_relevancy_score = Column(Float, nullable=True)
    answer_correctness_score = Column(Float, nullable=True)
    context_precision_score = Column(Float, nullable=True)
    context_recall_score = Column(Float, nullable=True)
    recall_at_k_score = Column(Float, nullable=True)
    ndcg_at_k_score = Column(Float, nullable=True)
    input_tokens = Column(Integer, nullable=False, default=0)
    cached_input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    snapshot_json = Column(Text, nullable=False, default="{}")
    langfuse_run_name = Column(String(200), nullable=True)
    langfuse_dataset_name = Column(String(200), nullable=True)
    langfuse_dataset_run_url = Column(String(1000), nullable=True)
    run_key = Column(String(500), nullable=True)
    cancel_requested = Column(Boolean, nullable=False, default=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    case_id = Column(Integer, ForeignKey("evaluation_cases.id", ondelete="SET NULL"), nullable=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False, default="")
    sources_json = Column(Text, nullable=False, default="[]")
    retrieval_score = Column(Float, nullable=False, default=0)
    fact_score = Column(Float, nullable=False, default=0)
    faithfulness_score = Column(Float, nullable=True)
    answer_relevancy_score = Column(Float, nullable=True)
    answer_correctness_score = Column(Float, nullable=True)
    context_precision_score = Column(Float, nullable=True)
    context_recall_score = Column(Float, nullable=True)
    recall_at_k_score = Column(Float, nullable=True)
    ndcg_at_k_score = Column(Float, nullable=True)
    input_tokens = Column(Integer, nullable=False, default=0)
    cached_input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
