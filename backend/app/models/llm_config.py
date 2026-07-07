"""
智答引擎（ZhiDa Engine）—— LLM 配置数据库模型

支持多模型配置（主模型 + 降级模型），厂商模板自动填充 + 全自定义双模式。
所有配置存储在本地 SQLite 数据库中。
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Text, ForeignKey, Enum as SAEnum,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class LLMConfig(Base):
    """
    LLM 模型配置表 —— 存储用户配置的 LLM 模型

    每个 Agent 可以独立配置自己的 LLM 模型。
    支持主模型 + 降级模型双配置。

    字段说明：
    - is_primary: 是否为主模型（每个 Agent 只有一个主模型）
    - is_fallback: 是否为降级模型（主模型不可用时自动切换）
    - provider_id: 厂商 ID，对应 ProviderTemplate.provider_id
    - provider_name: 厂商显示名称（自定义时用户自行填写）
    - base_url: API 基础地址（自动填充或用户自定义）
    - model_name: 模型名称
    - api_key: API Key（加密存储）
    - is_active: 是否启用
    """

    __tablename__ = "llm_configs"

    # 主键
    id = Column(Integer, primary_key=True, autoincrement=True)

    # 关联 Agent（可空，全局配置时 agent_id 为 NULL）
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=True)

    # 模型角色
    is_primary = Column(Boolean, default=False, comment="是否为主模型")
    is_fallback = Column(Boolean, default=False, comment="是否为降级模型")

    # 厂商信息
    provider_id = Column(String(50), nullable=False, default="custom", comment="厂商 ID")
    provider_name = Column(String(100), nullable=False, default="自定义", comment="厂商显示名称")

    # 连接配置
    base_url = Column(String(500), nullable=False, default="", comment="API 基础地址")
    model_name = Column(String(100), nullable=False, default="", comment="模型名称")
    api_key = Column(Text, nullable=False, default="", comment="API Key（加密存储）")

    # 额外配置（JSON 格式，用于存储 temperature、max_tokens 等参数）
    extra_config = Column(Text, nullable=True, comment="额外配置（JSON 格式）")

    # 状态
    is_active = Column(Boolean, default=True, comment="是否启用")
    last_test_at = Column(DateTime, nullable=True, comment="最后一次测试连接时间")
    last_test_success = Column(Boolean, nullable=True, comment="最后一次测试连接是否成功")

    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    # 关联关系
    agent = relationship("Agent", back_populates="llm_configs")

    def __repr__(self):
        return f"<LLMConfig(id={self.id}, provider={self.provider_name}, model={self.model_name}, primary={self.is_primary})>"


class ProviderConfig(Base):
    """
    厂商配置快照表 —— 存储厂商模板的用户自定义覆盖

    当用户选择内置厂商模板后修改了某些字段（如 base_url），
    这些修改会被存储到此表中，下次选择该厂商时恢复用户的修改。
    """

    __tablename__ = "provider_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider_id = Column(String(50), nullable=False, unique=True, comment="厂商 ID")
    custom_base_url = Column(String(500), nullable=True, comment="用户自定义的 Base URL")
    custom_model_name = Column(String(100), nullable=True, comment="用户自定义的默认模型")
    custom_api_key = Column(Text, nullable=True, comment="用户保存的 API Key")

    # 时间戳
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<ProviderConfig(provider_id={self.provider_id})>"