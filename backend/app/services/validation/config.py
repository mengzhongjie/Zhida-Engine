"""
智答引擎（ZhiDa Engine）—— 格式检查配置

从全局 settings 读取格式校验相关配置，封装为 ValidationConfig dataclass。
"""

from dataclasses import dataclass, field
from typing import Optional

from app.core.config import settings


@dataclass
class ValidationConfig:
    """文档格式校验配置

    从全局 Settings 的 ZHIDA_FORMAT_* 环境变量读取。
    使用 dataclass 避免与 Settings 循环依赖。
    """

    # 总开关
    enabled: bool = True

    # 严格模式：类型不匹配直接拒绝上传
    strict: bool = True

    # 文件大小上限（MB）
    max_file_size_mb: int = 100

    # 解析后最小文本长度（低于此值标记为空）
    min_text_length: int = 10

    # 乱码比例阈值（0-1），超过则标记警告
    garbage_threshold: float = 0.5

    # 解析结果为空时自动标记失败
    auto_reject_empty: bool = True

    # 综合质量评分最低通过线（0-100）
    min_quality_score: int = 10

    @classmethod
    def from_settings(cls) -> "ValidationConfig":
        """从全局 settings 读取配置"""
        return cls(
            enabled=settings.ENABLE_FORMAT_CHECK,
            strict=settings.FORMAT_CHECK_STRICT,
            max_file_size_mb=settings.FORMAT_MAX_FILE_SIZE_MB,
            min_text_length=settings.FORMAT_MIN_TEXT_LENGTH,
            garbage_threshold=settings.FORMAT_GARBAGE_THRESHOLD,
            auto_reject_empty=settings.FORMAT_AUTO_REJECT_EMPTY,
            min_quality_score=settings.FORMAT_MIN_QUALITY_SCORE,
        )


# 缓存配置实例
_validation_config: Optional[ValidationConfig] = None


def get_validation_config() -> ValidationConfig:
    """获取格式校验配置（惰性加载 + 缓存）"""
    global _validation_config
    if _validation_config is None:
        _validation_config = ValidationConfig.from_settings()
    return _validation_config


def reload_validation_config() -> ValidationConfig:
    """重新加载配置（用于运行时配置变更）"""
    global _validation_config
    _validation_config = ValidationConfig.from_settings()
    return _validation_config
