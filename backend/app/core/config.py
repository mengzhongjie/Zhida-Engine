"""
智答引擎（ZhiDa Engine）全局配置

所有数据存储在用户本地目录，支持 Windows .exe 打包后运行。
配置通过环境变量 + 配置文件 + 数据库三层管理。
"""

import os
import sys
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings


# 获取应用数据目录
# Windows: C:\Users\<用户名>\AppData\Local\ZhidaEngine\
# macOS:   ~/Library/Application Support/ZhidaEngine/
# Linux:   ~/.local/share/ZhidaEngine/
def get_app_data_dir() -> Path:
    """获取应用数据目录，确保目录存在"""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".local" / "share"

    data_dir = base / "ZhidaEngine"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


class Settings(BaseSettings):
    """应用全局配置 —— 所有配置项有默认值，开箱即用"""

    # ---- 应用基础 ----
    APP_NAME: str = "智答引擎"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False

    # ---- 数据目录 ----
    DATA_DIR: Path = get_app_data_dir()

    # ---- 数据库 ----
    # SQLite 数据库文件路径，存储在应用数据目录
    DATABASE_URL: str = ""

    @property
    def db_url(self) -> str:
        """获取数据库连接 URL"""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        db_path = self.DATA_DIR / "zhida_engine.db"
        return f"sqlite+aiosqlite:///{db_path}"

    # ---- 向量数据库 ----
    # ChromaDB 持久化目录
    CHROMA_PERSIST_DIR: str = ""

    @property
    def chroma_dir(self) -> str:
        """获取 ChromaDB 持久化目录"""
        if self.CHROMA_PERSIST_DIR:
            return self.CHROMA_PERSIST_DIR
        chroma_dir = self.DATA_DIR / "chroma_db"
        chroma_dir.mkdir(parents=True, exist_ok=True)
        return str(chroma_dir)

    # ---- 缓存 ----
    # diskcache 缓存目录
    CACHE_DIR: str = ""

    @property
    def cache_dir(self) -> str:
        """获取缓存目录"""
        if self.CACHE_DIR:
            return self.CACHE_DIR
        cache_dir = self.DATA_DIR / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return str(cache_dir)

    # ---- 服务端口 ----
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 18900  # 本地回环，不对外暴露

    # ---- Embedding 模型 ----
    # 默认使用本地 BGE 模型，无需 API Key
    EMBEDDING_MODE: str = "local"  # local / cloud
    EMBEDDING_MODEL: str = "BAAI/bge-large-zh-v1.5"
    EMBEDDING_DEVICE: str = "cpu"  # cpu / cuda
    # 云端 Embedding 配置（OpenAI 兼容）
    EMBEDDING_CLOUD_BASE_URL: str = ""
    EMBEDDING_CLOUD_API_KEY: str = ""
    EMBEDDING_CLOUD_MODEL: str = "text-embedding-3-small"
    EMBEDDING_CLOUD_DIMENSION: int = 1536

    # ---- 日志 ----
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = ""

    @property
    def log_dir(self) -> str:
        """获取日志目录"""
        if self.LOG_DIR:
            return self.LOG_DIR
        log_dir = self.DATA_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return str(log_dir)

    # ---- 模块开关 ----
    # 所有重功能均有开关，用户根据实际需求自由组合
    ENABLE_SINGLE_FLIGHT: bool = True  # 幂等请求合并
    ENABLE_GRAPH_RETRIEVAL: bool = True  # 图检索增强
    ENABLE_RERANK: bool = True  # 重排序
    ENABLE_STREAMING: bool = True  # 流式输出
    ENABLE_AUTO_LEARNING: bool = True  # 自动学习群聊知识
    ENABLE_SOURCE_CITATION: bool = True  # 回答后附带消息来源
    ENABLE_AUTO_MENTION: bool = True  # 回答不了时自动 @ 指定用户
    ENABLE_AUDIO_PARSE: bool = False  # 音频解析（实验性，默认关闭）
    ENABLE_IMAGE_PARSE: bool = False  # 图片解析（实验性，默认关闭）

    # ---- 安全配置 ----
    ENABLE_RATE_LIMIT: bool = True  # 限流总开关
    ENABLE_LOCAL_ONLY: bool = True  # 仅允许本地请求
    MAX_UPLOAD_SIZE_MB: int = 100  # 最大上传文件大小
    MAX_REQUEST_SIZE_MB: int = 10  # 最大请求体大小
    API_KEY_ENCRYPT_ENABLED: bool = True  # API Key 加密存储

    # ---- 限流配置 ----
    RATE_LIMIT_TOKEN_RATE: float = 10.0  # 令牌桶速率（令牌/秒）
    RATE_LIMIT_TOKEN_CAPACITY: int = 3  # 令牌桶容量
    RATE_LIMIT_WINDOW_SIZE: int = 60  # 滑动窗口大小（秒）
    RATE_LIMIT_WINDOW_MAX: int = 5  # 窗口内最大请求数
    RATE_LIMIT_COOLDOWN: int = 300  # 问题冷却时间（秒）
    RATE_LIMIT_SILENT_ENABLED: bool = True  # 是否启用静默时段
    RATE_LIMIT_PRIVATE_RELAXED: bool = True  # 私聊是否放宽限制

    model_config = {
        "env_prefix": "ZHIDA_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


# 全局配置单例
settings = Settings()