"""
智答引擎（ZhiDa Engine）—— 向量化配置 Pydantic Schema

用于 Embedding 模型配置的请求/响应数据校验和序列化。
仅支持云端 Embedding API（OpenAI 兼容）。
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field


# ============================================================
# Embedding 配置 Schema
# ============================================================

class EmbeddingConfigOut(BaseModel):
    """
    Embedding 配置输出

    包含当前使用的向量化模型类型、参数等信息。
    """
    mode: Literal["cloud"] = Field("cloud", description="向量化模式：云端 API")

    # 云端 API 配置
    cloud_base_url: str = Field("", description="云端 API 基础地址")
    cloud_api_key: str = Field("", description="云端 API Key（脱敏后返回）")
    cloud_model: str = Field("", description="云端模型名称")
    cloud_dimension: int = Field(0, description="向量维度")

    # 状态
    is_ready: bool = Field(False, description="是否就绪（模型已加载）")
    current_model: str = Field("", description="当前使用的模型名称")
    current_dimension: int = Field(0, description="当前向量维度")


class EmbeddingConfigUpdate(BaseModel):
    """
    更新 Embedding 配置请求
    """
    mode: Optional[Literal["cloud"]] = Field(None, description="向量化模式：云端 API")
    cloud_base_url: Optional[str] = Field(None, description="云端 API 基础地址")
    cloud_api_key: Optional[str] = Field(None, description="云端 API Key（空字符串表示不修改）")
    cloud_model: Optional[str] = Field(None, description="云端模型名称")
    cloud_dimension: Optional[int] = Field(None, description="向量维度")


class EmbeddingTestRequest(BaseModel):
    """
    测试 Embedding 连接请求
    """
    mode: Literal["cloud"] = Field("cloud", description="测试云端 API")
    cloud_base_url: Optional[str] = Field(None, description="云端 API 基础地址")
    cloud_api_key: Optional[str] = Field(None, description="云端 API Key")
    cloud_model: Optional[str] = Field(None, description="云端模型名称")


class EmbeddingTestResponse(BaseModel):
    """
    测试 Embedding 连接响应
    """
    success: bool
    message: str
    latency_ms: float = 0.0
    dimension: int = 0
