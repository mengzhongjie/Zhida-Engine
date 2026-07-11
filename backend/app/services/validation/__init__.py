"""
智答引擎（ZhiDa Engine）—— 文档格式检查与质量保障模块

提供上传前预检（magic bytes 格式校验、文件名清洗、损坏检测）
和解析后质检（空文本/乱码/完整度/语言/结构评分）。

所有检查默认启用，可通过 ZHIDA_ENABLE_FORMAT_CHECK=false 关闭。
"""

from app.services.validation.config import ValidationConfig, get_validation_config
from app.services.validation.precheck import UploadPreChecker
from app.services.validation.file_validator import FileFormatValidator
from app.services.validation.quality_checker import ParseQualityChecker

__all__ = [
    "ValidationConfig",
    "get_validation_config",
    "UploadPreChecker",
    "FileFormatValidator",
    "ParseQualityChecker",
]
