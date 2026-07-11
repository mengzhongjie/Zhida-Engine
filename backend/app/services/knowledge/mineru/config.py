"""
智答引擎（ZhiDa Engine）—— MinerU 文档解析配置

从全局 settings 读取 MinerU 相关配置，封装为 MinerUConfig dataclass。
"""

from dataclasses import dataclass, field
from typing import Optional

from app.core.config import settings


@dataclass
class MinerUConfig:
    """MinerU 文档解析配置

    从全局 Settings 的 ZHIDA_MINERU_* 环境变量读取。
    使用 dataclass 而非 Pydantic 以避免与 Settings 自身的 Pydantic 循环依赖。
    """

    # 总开关（由 settings.ENABLE_MINERU 控制）
    enabled: bool = False

    # 部署模式
    mode: str = "embedded"  # embedded | service

    # 计算后端
    backend: str = "pipeline"  # pipeline | vlm-engine | hybrid-engine

    # 推理设备
    device: str = "cpu"  # cpu | cuda

    # OCR/解析语言
    languages: list[str] = field(default_factory=lambda: ["zh", "en"])

    # 独立服务地址
    service_url: str = "http://127.0.0.1:18901"

    # 服务请求超时
    service_timeout: int = 600

    # 使用 MinerU 处理的格式
    formats: set[str] = field(default_factory=lambda: {"pdf", "docx"})

    # 失败时降级
    fallback_on_failure: bool = True

    # 最大文件大小
    max_file_size_mb: int = 50

    # MinerU 专有格式（现有 FileType 枚举未覆盖的格式）
    # 这些格式必须有 MinerU 才能解析，否则直接报错
    mineru_only_formats: set[str] = field(default_factory=lambda: {
        "pptx", "ppt", "epub", "html", "htm",
        "png", "jpg", "jpeg", "bmp", "tiff", "webp",
    })

    @classmethod
    def from_settings(cls) -> "MinerUConfig":
        """从全局 settings 读取配置"""
        return cls(
            enabled=settings.ENABLE_MINERU,
            mode=settings.MINERU_MODE,
            backend=settings.MINERU_BACKEND,
            device=settings.MINERU_DEVICE,
            languages=[lang.strip() for lang in settings.MINERU_LANGUAGES.split(",") if lang.strip()],
            service_url=settings.MINERU_SERVICE_URL.rstrip("/"),
            service_timeout=settings.MINERU_SERVICE_TIMEOUT,
            formats={fmt.strip().lower() for fmt in settings.MINERU_FORMATS.split(",") if fmt.strip()},
            fallback_on_failure=settings.MINERU_FALLBACK_ON_FAILURE,
            max_file_size_mb=settings.MINERU_MAX_FILE_SIZE_MB,
        )

    def can_handle_format(self, ext: str) -> bool:
        """检查某个文件扩展名是否在 MinerU 处理范围内"""
        ext = ext.lower().lstrip(".")
        return ext in self.formats or ext in self.mineru_only_formats

    def is_mineru_only_format(self, ext: str) -> bool:
        """检查是否 MinerU 专有格式（现有解析器不支持）"""
        return ext.lower().lstrip(".") in self.mineru_only_formats


# 缓存配置实例（避免重复读取 settings）
_mineru_config: Optional[MinerUConfig] = None


def get_mineru_config() -> MinerUConfig:
    """获取 MinerU 配置（惰性加载 + 缓存）"""
    global _mineru_config
    if _mineru_config is None:
        _mineru_config = MinerUConfig.from_settings()
    return _mineru_config


def reload_mineru_config() -> MinerUConfig:
    """重新加载配置（用于运行时配置变更）"""
    global _mineru_config
    _mineru_config = MinerUConfig.from_settings()
    return _mineru_config
