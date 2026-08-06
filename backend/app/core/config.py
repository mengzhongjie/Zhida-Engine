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


# 与启动目录无关，始终读取 backend/.env，便于本地与容器部署。
_BACKEND_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


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
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"
    TRUSTED_HOSTS: str = "localhost,127.0.0.1,::1"
    # 这些主机名返回仅含用户对话功能的独立前端；管理端使用其余受信主机名。
    # 生产环境示例：app.example.com。保持 Cookie 为 host-only，避免跨端携带。
    USER_APP_HOSTS: str = ""
    # 仅当 TCP 对端属于该列表时，才接受 Nginx 写入的 X-Real-IP / X-Forwarded-Proto。
    # Docker 中宿主机 Nginx 转发到容器时，通常需在生产 .env 中额外加入 172.17.0.1。
    TRUSTED_PROXY_IPS: str = "127.0.0.1,::1"

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def trusted_hosts(self) -> list[str]:
        return [host.strip() for host in self.TRUSTED_HOSTS.split(",") if host.strip()]

    @property
    def user_app_hosts(self) -> set[str]:
        return {host.strip().lower() for host in self.USER_APP_HOSTS.split(",") if host.strip()}

    @property
    def trusted_proxy_ips(self) -> set[str]:
        return {ip.strip() for ip in self.TRUSTED_PROXY_IPS.split(",") if ip.strip()}

    # ---- 云端 Embedding 模型 ----
    EMBEDDING_MODE: str = "cloud"
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
    ENABLE_STREAMING: bool = True  # 预留给内部调用的模型流式能力
    ENABLE_SOURCE_CITATION: bool = True  # 回答后附带消息来源
    ENABLE_MINERU: bool = False  # MinerU 文档解析（可选，需安装 magic-pdf）

    # ---- 安全配置 ----
    ENABLE_RATE_LIMIT: bool = True  # 限流总开关
    MAX_UPLOAD_SIZE_MB: int = 100  # 最大上传文件大小
    MAX_REQUEST_SIZE_MB: int = 10  # 最大请求体大小
    API_KEY_ENCRYPT_ENABLED: bool = True  # API Key 加密存储

    ADMIN_BOOTSTRAP_USERNAME: str = ""
    ADMIN_BOOTSTRAP_PASSWORD: str = ""
    AUTH_SESSION_SECRET: str = ""
    AUTH_USER_SESSION_DAYS: int = 7
    AUTH_ADMIN_SESSION_HOURS: int = 8
    # 公网请求必须由 HTTPS 反向代理进入；localhost/回环地址保留 HTTP 开发能力。
    AUTH_REQUIRE_HTTPS: bool = True

    # ---- 网络检索（RAG 未命中时的补充能力）----
    WEB_SEARCH_ENABLED: bool = False
    WEB_SEARCH_PROVIDER: str = "tavily"
    WEB_SEARCH_API_KEY: str = ""
    WEB_SEARCH_MAX_RESULTS: int = 3

    # ---- 仅开发部署使用的 Langfuse 观测（不在应用内配置或展示）----
    LANGFUSE_ENABLED: bool = False
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_EVALUATOR_ENABLED: bool = False
    LANGFUSE_EVALUATOR_MODEL_CONFIG_ID: int | None = None

    # ---- 限流配置 ----
    RATE_LIMIT_TOKEN_RATE: float = 10.0  # 令牌桶速率（令牌/秒）
    RATE_LIMIT_TOKEN_CAPACITY: int = 3  # 令牌桶容量
    RATE_LIMIT_WINDOW_SIZE: int = 60  # 滑动窗口大小（秒）
    RATE_LIMIT_WINDOW_MAX: int = 5  # 窗口内最大请求数
    RATE_LIMIT_COOLDOWN: int = 300  # 问题冷却时间（秒）
    RATE_LIMIT_SILENT_ENABLED: bool = True  # 是否启用静默时段
    RATE_LIMIT_PRIVATE_RELAXED: bool = True  # 私聊是否放宽限制

    # ---- 在线问答并发保护 ----
    # 单机 SQLite/Chroma 部署优先保护正在对话的用户。超出部分在 SSE 建立后排队，
    # 队列超时才返回繁忙提示，不让突发请求同时挤爆模型网关或本机资源。
    QA_MAX_CONCURRENT_STREAMS: int = 10
    QA_MAX_STREAM_QUEUE: int = 20
    QA_STREAM_QUEUE_TIMEOUT_SECONDS: int = 45

    # ---- MinerU 文档解析（可选，默认关闭）----
    # MinerU 是上海 AI Lab 开源的一站式文档解析引擎，支持 PDF/DOCX/PPTX/EPUB/图片等格式
    # 两种部署模式：embedded（直接调用 Python API，需安装 magic-pdf）| service（通过 HTTP 调用独立 MinerU 服务）
    MINERU_MODE: str = "embedded"
    """MinerU 部署模式: embedded | service"""
    MINERU_BACKEND: str = "pipeline"
    """MinerU 计算后端: pipeline(CPU可用) | vlm-engine(GPU高精度) | hybrid-engine(GPU)"""
    MINERU_DEVICE: str = "cpu"
    """MinerU 推理设备: cpu | cuda"""
    MINERU_LANGUAGES: str = "zh,en"
    """MinerU OCR/解析语言列表，逗号分隔"""
    MINERU_SERVICE_URL: str = "http://127.0.0.1:18901"
    """MinerU 独立服务地址（仅 service 模式生效）"""
    MINERU_SERVICE_TIMEOUT: int = 600
    """MinerU 服务请求超时（秒）"""
    # PDF 是 MinerU 最稳定的输入；DOCX/XLSX 默认仍使用现有专用解析器。
    # 需要将某一格式交给 MinerU 时，可在环境变量中显式追加。
    MINERU_FORMATS: str = "pdf"
    """使用 MinerU 处理的文件格式，逗号分隔"""
    MINERU_FALLBACK_ON_FAILURE: bool = True
    """MinerU 失败时自动降级到本地解析器"""
    MINERU_MAX_FILE_SIZE_MB: int = 50
    """MinerU 处理的最大文件大小（MB），超过此值使用本地解析器"""

    # ---- 文档格式校验 ----
    # 基于 magic bytes + 解析结果多维评分
    ENABLE_FORMAT_CHECK: bool = True
    """格式校验总开关"""
    FORMAT_CHECK_STRICT: bool = True
    """严格模式：文件类型不匹配直接拒绝上传"""
    FORMAT_MAX_FILE_SIZE_MB: int = 100
    """上传文件大小上限（MB）"""
    FORMAT_MIN_TEXT_LENGTH: int = 10
    """解析后最小文本长度（字符），低于此值标记为空"""
    FORMAT_GARBAGE_THRESHOLD: float = 0.5
    """乱码比例阈值（0-1），超过则标记警告"""
    FORMAT_AUTO_REJECT_EMPTY: bool = True
    """解析结果为空时自动标记失败"""
    FORMAT_MIN_QUALITY_SCORE: int = 10
    """综合质量评分最低通过线（0-100）"""

    # ---- 轻量文档任务可靠性 ----
    DOCUMENT_PROCESS_TIMEOUT_BASE_SECONDS: int = 90
    DOCUMENT_PROCESS_TIMEOUT_PER_MB_SECONDS: int = 12
    DOCUMENT_PROCESS_TIMEOUT_MAX_SECONDS: int = 900
    DOCUMENT_PROCESS_MAX_ATTEMPTS: int = 3
    DOCUMENT_PROCESS_RETRY_BASE_SECONDS: int = 3

    model_config = {
        "env_prefix": "ZHIDA_",
        "env_file": _BACKEND_ENV_FILE,
        "env_file_encoding": "utf-8",
    }


# 全局配置单例
settings = Settings()
