"""
智答引擎（ZhiDa Engine）—— MinerU 文档解析包

MinerU（OpenDataLab）是一站式文档解析引擎，支持 PDF/DOCX/PPTX/EPUB/HTML/图片等格式。
"""

from app.services.knowledge.mineru.parser import MinerUParser
from app.services.knowledge.mineru.config import MinerUConfig, get_mineru_config
from app.services.knowledge.mineru.backend import (
    MinerUBackend,
    EmbeddedMinerUBackend,
    HttpMinerUBackend,
    create_mineru_backend,
)

__all__ = [
    "MinerUParser",
    "MinerUConfig",
    "MinerUBackend",
    "EmbeddedMinerUBackend",
    "HttpMinerUBackend",
    "create_mineru_backend",
    "get_mineru_config",
]
