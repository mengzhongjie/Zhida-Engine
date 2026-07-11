"""
智答引擎（ZhiDa Engine）—— MinerU 解析器

MinerUParser 封装 MinerU 后端的调用，将原始输出转换为项目的 ParseResult。
下游 splitter/router 无需感知 MinerU 的存在。
"""

import os
import time
from pathlib import Path
from typing import Optional, AsyncIterator

from loguru import logger

from app.services.knowledge.parser import ParseResult, ParseStatus, ParseChunk, FileType
from app.services.knowledge.mineru.config import MinerUConfig, get_mineru_config
from app.services.knowledge.mineru.backend import MinerUBackend, create_mineru_backend


class MinerUParser:
    """MinerU 解析器 —— 封装 MinerU 调用，输出项目统一的 ParseResult

    作为 DocumentParser 的可选解析策略，优先使用 MinerU 解析，
    失败时自动降级到现有解析器。

    Usage:
        config = get_mineru_config()
        backend = create_mineru_backend(config)
        parser = MinerUParser(backend, config)

        result = await parser.parse("document.pdf")
    """

    # MinerU 专有格式（现有 FileType 枚举未覆盖）
    MINERU_ONLY_EXTENSIONS = {
        "pptx", "ppt", "epub", "html", "htm",
        "png", "jpg", "jpeg", "bmp", "tiff", "webp",
    }

    def __init__(self, backend: MinerUBackend, config: MinerUConfig):
        self._backend = backend
        self._config = config

    @property
    def backend(self) -> MinerUBackend:
        return self._backend

    @property
    def config(self) -> MinerUConfig:
        return self._config

    def can_handle(self, ext_or_filetype: str) -> bool:
        """判断 MinerU 是否能处理该文件格式

        Args:
            ext_or_filetype: 文件扩展名 (如 "pdf") 或 FileType 枚举值
        """
        if isinstance(ext_or_filetype, FileType):
            ext = ext_or_filetype.value
        else:
            ext = ext_or_filetype.lower().lstrip(".")
        return self._config.can_handle_format(ext)

    def is_mineru_only_format(self, ext: str) -> bool:
        """判断是否是仅 MinerU 支持的格式"""
        return ext.lower().lstrip(".") in self.MINERU_ONLY_EXTENSIONS

    async def is_available(self) -> bool:
        """检查 MinerU 后端是否可用"""
        try:
            return await self._backend.is_available()
        except Exception:
            return False

    async def parse(self, file_path: str) -> ParseResult:
        """使用 MinerU 解析文档

        Args:
            file_path: 文件路径

        Returns:
            ParseResult 解析结果
        """
        start_time = time.time()
        file_name = Path(file_path).name
        file_size = os.path.getsize(file_path) / (1024 * 1024)

        logger.info(f"MinerU 开始解析: {file_name} (后端={self._backend.backend_type}, 大小={file_size:.1f}MB)")

        try:
            raw = await self._backend.parse(file_path)
            result = self._convert_to_parse_result(raw)
        except Exception as e:
            logger.error(f"MinerU 解析异常: {file_name}: {e}")
            result = ParseResult(
                status=ParseStatus.FAILED,
                error_message=f"MinerU 解析失败: {e}",
            )

        result.parse_time_ms = (time.time() - start_time) * 1000
        logger.info(
            f"MinerU 解析完成: {file_name}, "
            f"状态={result.status.value}, 耗时={result.parse_time_ms:.0f}ms, "
            f"文本长度={len(result.text)}"
        )

        return result

    async def parse_paginated(
        self,
        file_path: str,
        page_size: int = 5,
    ) -> AsyncIterator[ParseChunk]:
        """分页解析 —— 按页或按块输出

        注意：MinerU 本身不支持真正的增量分页，
        这里通过全量解析后按 pages 列表分块输出。
        """
        result = await self.parse(file_path)

        if result.status == ParseStatus.FAILED:
            logger.error(f"MinerU 分页解析失败: {result.error_message}")
            return

        # 如果有多页，按页输出
        if result.pages:
            for i, page_text in enumerate(result.pages):
                yield ParseChunk(
                    text=page_text,
                    metadata={
                        **result.metadata,
                        "page": i + 1,
                        "total_pages": len(result.pages),
                    },
                    chunk_index=i,
                )
        else:
            # 无分页信息，输出整个文本
            yield ParseChunk(
                text=result.text,
                metadata={**result.metadata, "page": 1, "total_pages": 1},
                chunk_index=0,
            )

    # ================================================================
    # MinerU 输出转换
    # ================================================================

    def _convert_to_parse_result(self, raw: dict) -> ParseResult:
        """将 MinerU 原始输出转换为 ParseResult

        MinerU 输出是 Markdown + JSON 结构，这里提取文本、页面、表格和元数据。
        """
        markdown = raw.get("markdown", "")

        # 没有提取到文本
        if not markdown.strip():
            return ParseResult(
                status=ParseStatus.SUCCESS,
                text="",
                metadata={
                    "parser": "mineru",
                    "parse_backend": raw.get("metadata", {}).get("backend", "unknown"),
                    "warning": "MinerU 返回空内容",
                },
            )

        # 分页内容
        pages = raw.get("pages", [])
        if not pages and markdown:
            pages = [markdown]  # 至少保持完整文本

        # 表格
        tables = raw.get("tables", [])

        # 元数据
        meta = raw.get("metadata", {})
        metadata = {
            "parser": "mineru",
            "parse_backend": meta.get("backend", self._backend.backend_type),
            "parse_mode": meta.get("mode", self._backend.backend_type),
            "total_pages": meta.get("total_pages", len(pages)),
        }

        # 检测内容特征
        if markdown:
            if "$$" in markdown or "$" in markdown:
                metadata["has_formulas"] = True
            if tables:
                metadata["has_tables"] = True
            if "```" in markdown:
                metadata["has_code"] = True

        # 保留原始 MinerU 元数据（不覆盖已设置的字段）
        for k, v in meta.items():
            if k not in metadata and isinstance(v, (str, int, float, bool)):
                metadata[k] = v

        return ParseResult(
            status=ParseStatus.SUCCESS,
            text=markdown,
            pages=pages if pages else [markdown],
            metadata=metadata,
            tables=tables,
        )


def create_mineru_parser() -> Optional[MinerUParser]:
    """创建 MinerU 解析器实例（若启用且可用）

    由 DocumentParser 在初始化时调用，返回 None 表示 MinerU 不可用。
    """
    config = get_mineru_config()
    if not config.enabled:
        return None

    try:
        backend = create_mineru_backend(config)
        return MinerUParser(backend, config)
    except Exception as e:
        logger.warning(f"MinerU 初始化失败，将使用本地解析器: {e}")
        return None
