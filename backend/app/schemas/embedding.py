"""
智答引擎（ZhiDa Engine）—— 向量化配置 Pydantic Schema

用于 Embedding 模型配置的请求/响应数据校验和序列化。
支持本地模型（BGE 等）和云端 API（OpenAI 兼容）两种模式。
"""

from typing import Optional
from pydantic import BaseModel, Field


# ============================================================
# Embedding 配置 Schema
# ============================================================

class EmbeddingConfigOut(BaseModel):
    """
    Embedding 配置输出

    包含当前使用的向量化模型类型、参数等信息。
    """
    # 模式: local（本地模型）/ cloud（云端 API）
    mode: str = Field("local", description="向量化模式: local=本地模型, cloud=云端API")

    # 本地模型配置
    local_model: str = Field("BAAI/bge-large-zh-v1.5", description="本地模型名称")
    local_device: str = Field("cpu", description="运行设备: cpu/cuda")

    # 云端 API 配置
    cloud_base_url: str = Field("", description="云端 API 基础地址")
    cloud_api_key: str = Field("", description="云端 API Key（脱敏后返回）")
    cloud_model: str = Field("text-embedding-3-small", description="云端模型名称")
    cloud_dimension: int = Field(1536, description="向量维度")

    # 状态
    is_ready: bool = Field(False, description="是否就绪（模型已加载）")
    current_model: str = Field("", description="当前使用的模型名称")
    current_dimension: int = Field(0, description="当前向量维度")


class EmbeddingConfigUpdate(BaseModel):
    """
    更新 Embedding 配置请求
    """
    mode: Optional[str] = Field(None, description="向量化模式: local/cloud")
    local_model: Optional[str] = Field(None, description="本地模型名称")
    local_device: Optional[str] = Field(None, description="运行设备: cpu/cuda")
    cloud_base_url: Optional[str] = Field(None, description="云端 API 基础地址")
    cloud_api_key: Optional[str] = Field(None, description="云端 API Key（空字符串表示不修改）")
    cloud_model: Optional[str] = Field(None, description="云端模型名称")
    cloud_dimension: Optional[int] = Field(None, description="向量维度")


class EmbeddingTestRequest(BaseModel):
    """
    测试 Embedding 连接请求
    """
    mode: str = Field(..., description="测试模式: local/cloud")
    local_model: Optional[str] = Field(None, description="本地模型名称")
    local_device: Optional[str] = Field(None, description="运行设备")
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
