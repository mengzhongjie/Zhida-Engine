"""混合文档解析路由测试：不依赖真实 MinerU 模型或网络服务。"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.knowledge.parser import DocumentParser, ParseResult, ParseStatus


class _SuccessfulMinerU:
    config = SimpleNamespace(max_file_size_mb=50, fallback_on_failure=True)

    def can_handle(self, extension: str) -> bool:
        return extension == "pdf"

    async def is_available(self) -> bool:
        return True

    async def parse(self, file_path: str) -> ParseResult:
        return ParseResult(
            status=ParseStatus.SUCCESS,
            text="# MinerU\n\n| A | B |\n| - | - |\n| 1 | 2 |",
            pages=["# MinerU"],
            tables=["| A | B |\n| - | - |\n| 1 | 2 |"],
            metadata={"parser": "mineru"},
        )

    async def parse_paginated(self, file_path: str, page_size: int):
        if False:
            yield None


class _FailingMinerU(_SuccessfulMinerU):
    def can_handle(self, extension: str) -> bool:
        return extension == "txt"

    async def parse(self, file_path: str) -> ParseResult:
        return ParseResult(status=ParseStatus.FAILED, error_message="simulated failure")


@pytest.mark.asyncio
async def test_pdf_prefers_available_mineru(tmp_path: Path):
    file_path = tmp_path / "sample.pdf"
    file_path.write_bytes(b"placeholder")

    result = await DocumentParser(mineru_parser=_SuccessfulMinerU()).parse(str(file_path))

    assert result.status == ParseStatus.SUCCESS
    assert result.metadata["parser"] == "mineru"
    assert "| A | B |" in result.text


@pytest.mark.asyncio
async def test_mineru_failure_falls_back_to_native_txt_parser(tmp_path: Path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("native fallback text", encoding="utf-8")

    result = await DocumentParser(mineru_parser=_FailingMinerU()).parse(str(file_path))

    assert result.status == ParseStatus.SUCCESS
    assert result.text == "native fallback text"
