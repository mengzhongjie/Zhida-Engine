"""
智答引擎（ZhiDa Engine）—— 向量化配置数据库模型

向量化配置为全局单例，存储在数据库中，支持持久化。
应用启动时从数据库加载配置，修改后自动保存。
"""

from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text

from app.core.database import Base


class EmbeddingConfig(Base):
    """
    向量化配置表 —— 全局单例，存储向量化相关配置

    只有一条记录（id=1），应用启动时加载，修改后更新。

    字段说明：
    - mode: 固定为 cloud
    - local_model/local_device: 历史兼容字段，不再使用
    - cloud_base_url: 云端 API 基础地址
    - cloud_api_key: 云端 API Key（加密存储）
    - cloud_model: 云端模型名称
    - cloud_dimension: 云端向量维度
    """

    __tablename__ = "embedding_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 模式
    mode = Column(String(20), default="cloud", comment="向量化模式：cloud")

    # 历史兼容字段；保留列以兼容已有 SQLite 数据库，不参与运行配置。
    local_model = Column(String(200), default="", comment="历史兼容字段")
    local_device = Column(String(20), default="", comment="历史兼容字段")

    # 云端 API 配置
    cloud_base_url = Column(String(500), default="", comment="云端 API 基础地址")
    cloud_api_key = Column(Text, default="", comment="云端 API Key（加密存储）")
    cloud_model = Column(String(200), default="text-embedding-3-small", comment="云端模型名称")
    cloud_dimension = Column(Integer, default=1536, comment="云端向量维度")

    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")
