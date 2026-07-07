"""
智答引擎（ZhiDa Engine）—— LLM 配置 Pydantic Schema

用于 API 请求/响应的数据校验和序列化。
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ============================================================
# 厂商模板 Schema（返回给前端展示）
# ============================================================

class ProviderTemplateOut(BaseModel):
    """厂商模板输出 —— 前端厂商选择下拉框使用"""
    provider_id: str = Field(..., description="厂商唯一标识")
    name: str = Field(..., description="厂商显示名称")
    category: str = Field(..., description="分类: cloud/local/custom")
    base_url: str = Field(..., description="API 基础地址")
    default_model: str = Field(..., description="默认推荐模型")
    available_models: list[str] = Field(default_factory=list, description="可用模型列表")
    requires_api_key: bool = Field(..., description="是否需要 API Key")
    api_key_label: str = Field("", description="API Key 字段标签")
    icon: str = Field("🔧", description="厂商图标")
    description: str = Field("", description="厂商简介")
    docs_url: str = Field("", description="官方文档链接")


class ProviderTemplateListOut(BaseModel):
    """厂商模板列表输出 —— 按分类分组"""
    cloud: list[ProviderTemplateOut] = Field(default_factory=list, description="云端厂商")
    local: list[ProviderTemplateOut] = Field(default_factory=list, description="本地厂商")
    custom: list[ProviderTemplateOut] = Field(default_factory=list, description="自定义")


# ============================================================
# LLM 配置 Schema
# ============================================================

class LLMConfigCreate(BaseModel):
    """创建 LLM 配置"""
    agent_id: Optional[int] = Field(None, description="Agent ID，空=全局配置")
    provider_id: str = Field(..., description="厂商 ID")
    provider_name: Optional[str] = Field(None, description="厂商显示名称（自定义时必填）")
    base_url: Optional[str] = Field(None, description="API 基础地址（自定义时必填）")
    model_name: str = Field(..., description="模型名称")
    api_key: Optional[str] = Field(None, description="API Key")
    is_primary: bool = Field(False, description="是否为主模型")
    is_fallback: bool = Field(False, description="是否为降级模型")
    extra_config: Optional[str] = Field(None, description="额外配置（JSON 格式）")
    # API 限流配置
    max_tokens_per_request: int = Field(4096, description="单次请求最大 Token 数")
    max_requests_per_minute: int = Field(30, description="每分钟最大请求数")
    max_tokens_per_minute: int = Field(100000, description="每分钟最大 Token 数")
    max_tokens_per_day: int = Field(1000000, description="每日最大 Token 数")


class LLMConfigUpdate(BaseModel):
    """更新 LLM 配置"""
    provider_name: Optional[str] = Field(None, description="厂商显示名称")
    base_url: Optional[str] = Field(None, description="API 基础地址")
    model_name: Optional[str] = Field(None, description="模型名称")
    api_key: Optional[str] = Field(None, description="API Key")
    is_primary: Optional[bool] = Field(None, description="是否为主模型")
    is_fallback: Optional[bool] = Field(None, description="是否为降级模型")
    is_active: Optional[bool] = Field(None, description="是否启用")
    extra_config: Optional[str] = Field(None, description="额外配置（JSON 格式）")
    # API 限流配置
    max_tokens_per_request: Optional[int] = Field(None, description="单次请求最大 Token 数")
    max_requests_per_minute: Optional[int] = Field(None, description="每分钟最大请求数")
    max_tokens_per_minute: Optional[int] = Field(None, description="每分钟最大 Token 数")
    max_tokens_per_day: Optional[int] = Field(None, description="每日最大 Token 数")


class LLMConfigOut(BaseModel):
    """LLM 配置输出"""
    id: int
    agent_id: Optional[int] = None
    provider_id: str
    provider_name: str
    base_url: str
    model_name: str
    api_key: str = ""  # 脱敏后的 API Key（只显示前后几位）
    is_primary: bool
    is_fallback: bool
    is_active: bool
    extra_config: Optional[str] = None
    # API 限流配置
    max_tokens_per_request: int = 4096
    max_requests_per_minute: int = 30
    max_tokens_per_minute: int = 100000
    max_tokens_per_day: int = 1000000
    # 使用统计
    tokens_used_today: int = 0
    requests_today: int = 0
    last_test_at: Optional[datetime] = None
    last_test_success: Optional[bool] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ============================================================
# 测试连接 Schema
# ============================================================

class TestConnectionRequest(BaseModel):
    """测试连接请求"""
    base_url: str = Field(..., description="API 基础地址")
    api_key: str = Field(default="", description="API Key")
    model_name: str = Field(..., description="模型名称")


class TestConnectionResponse(BaseModel):
    """测试连接响应"""
    success: bool = Field(..., description="是否成功")
    message: str = Field(..., description="结果消息")
    latency_ms: float = Field(..., description="延迟（毫秒）")
    model: str = Field(..., description="测试的模型名称")


# ============================================================
# 厂商自动填充 Schema
# ============================================================

class ProviderAutoFillRequest(BaseModel):
    """厂商自动填充请求"""
    provider_id: str = Field(..., description="厂商 ID")


class ProviderAutoFillResponse(BaseModel):
    """厂商自动填充响应 —— 选择厂商后返回的默认值"""
    provider_id: str
    provider_name: str
    base_url: str
    default_model: str
    available_models: list[str]
    requires_api_key: bool
    api_key_label: str
    category: str