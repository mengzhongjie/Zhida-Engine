"""
智答引擎（ZhiDa Engine）—— 上传前预检

在文件进入解析流程之前做三合一检查：
1. 文件格式校验（magic bytes + 扩展名匹配）
2. 文件名清洗（移除路径穿越/危险字符）
3. 文件完整性检查（空文件、损坏检测）
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from loguru import logger

from app.services.validation.file_validator import FileFormatValidator, FormatValidationResult
from app.services.validation.config import ValidationConfig, get_validation_config


# 文件名中需要移除的危险字符（保留可读性）
_FILENAME_DANGEROUS_CHARS = re.compile(r'[\\/:*?"<>|]')

# 路径穿越检测
_PATH_TRAVERSAL_PATTERN = re.compile(r'(\.\./)')

# 文件名最大长度
_MAX_FILENAME_LENGTH = 200


@dataclass
class PreCheckReport:
    """上传前预检报告"""
    passed: bool = False
    real_type: str = ""
    declared_type: str = ""
    type_mismatch: bool = False
    safe_filename: str = ""
    file_size_bytes: int = 0
    is_corrupted: bool = False
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class UploadPreChecker:
    """上传前预检器

    在文件写入磁盘和进入解析链路前执行安全检查。
    """

    def __init__(
        self,
        validator: Optional[FileFormatValidator] = None,
        config: Optional[ValidationConfig] = None,
    ):
        self._validator = validator or FileFormatValidator()
        self._config = config or get_validation_config()

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """清洗文件名：移除危险字符，限制长度

        策略：
        - 移除路径穿越 (../)
        - 移除危险字符 \\/:*?"<>|
        - 移除控制字符
        - 限制最大长度 200
        - 保留可读性（中文、字母、数字、连字符、下划线、点）

        Args:
            filename: 原始文件名

        Returns:
            清洗后的安全文件名
        """
        if not filename:
            return "untitled"

        # 路径穿越检测 + 移除
        filename = _PATH_TRAVERSAL_PATTERN.sub("_", filename)

        # 移除危险字符
        filename = _FILENAME_DANGEROUS_CHARS.sub("_", filename)

        # 移除控制字符（保留中文、字母、数字、空格、连字符、下划线、点）
        cleaned = []
        for c in filename:
            cp = ord(c)
            if cp >= 0x4E00 and cp <= 0x9FFF:  # 中文
                cleaned.append(c)
            elif c.isalnum() or c in " ._-":
                cleaned.append(c)
            elif cp in (0x3000, 0x3001, 0x3002):  # 中文标点
                cleaned.append(c)
            else:
                cleaned.append("_")

        filename = "".join(cleaned)

        # 去除前导点和空白
        filename = filename.lstrip(". ").strip()

        # 限制长度
        if len(filename) > _MAX_FILENAME_LENGTH:
            name, ext = os.path.splitext(filename)
            # 保留扩展名
            max_name_len = _MAX_FILENAME_LENGTH - len(ext)
            if max_name_len < 10:
                max_name_len = 10
            filename = name[:max_name_len] + ext

        return filename or "untitled"

    @staticmethod
    def check_corrupted(file_bytes: bytes, real_type: str) -> tuple[bool, str]:
        """检查文件是否损坏

        对不同格式做基本的完整性校验。

        Returns:
            (is_corrupted: bool, message: str)
        """
        if not file_bytes:
            return True, "文件内容为空"

        # PDF 完整性：检查文件尾标记
        if real_type == "pdf":
            tail = file_bytes[-2048:] if len(file_bytes) > 2048 else file_bytes
            if b"%%EOF" not in tail:
                return True, "PDF 文件不完整（缺少 %%EOF 结束标记）"

        # ZIP 容器完整性
        if real_type in {"docx", "xlsx", "pptx", "epub", "zip"}:
            try:
                import zipfile
                import io
                with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
                    # 尝试读取所有条目，触发完整性检查
                    bad = zf.testzip()
                    if bad:
                        return True, f"ZIP 容器损坏: 文件 {bad} 校验失败"
            except zipfile.BadZipFile:
                return True, "ZIP 文件已损坏（BadZipFile）"
            except Exception as e:
                return True, f"ZIP 完整性检查失败: {e}"

        # PNG 完整性
        if real_type == "png":
            # 检查 IEND 块尾
            if file_bytes[-12:] != b"\x00\x00\x00\x00IEND\xae\x42\x60\x82":
                return True, "PNG 文件不完整（缺少 IEND 块）"

        return False, ""

    def check(
        self,
        file_bytes: bytes,
        filename: str,
    ) -> PreCheckReport:
        """执行上传前预检

        Args:
            file_bytes: 文件二进制内容
            filename: 原始文件名

        Returns:
            PreCheckReport 包含完整检查结果
        """
        report = PreCheckReport()
        report.file_size_bytes = len(file_bytes)
        report.declared_type = Path(filename).suffix.lower().lstrip(".") if filename else ""

        # 1. 文件名清洗
        report.safe_filename = self.sanitize_filename(filename)

        # 2. 文件大小检查
        max_bytes = self._config.max_file_size_mb * 1024 * 1024
        if len(file_bytes) > max_bytes:
            report.errors.append(
                f"文件大小超过限制: {len(file_bytes) / 1024 / 1024:.0f}MB > {self._config.max_file_size_mb}MB"
            )

        # 3. 空文件检查
        if len(file_bytes) == 0:
            report.errors.append("文件内容为空")

        # 4. Magic bytes 格式校验
        fmt_result = self._validator.detect(file_bytes)
        report.real_type = fmt_result.real_type
        report.type_mismatch = False

        if report.declared_type:
            ext_passed, ext_msg = self._validator.validate_extension(
                fmt_result.real_type,
                report.declared_type,
                strict=self._config.strict,
            )
            if not ext_passed:
                report.type_mismatch = True
                report.errors.append(ext_msg)
            elif ext_msg and "不匹配" in ext_msg:
                report.warnings.append(ext_msg)
                report.type_mismatch = True

        # 5. 文件损坏检查
        if report.real_type and report.real_type != "unknown":
            corrupted, corruption_msg = self.check_corrupted(file_bytes, report.real_type)
            if corrupted:
                report.is_corrupted = True
                report.errors.append(corruption_msg)

        # 6. 汇总判定
        report.passed = len(report.errors) == 0

        if report.passed and report.warnings:
            for w in report.warnings:
                logger.warning(f"格式预检警告 [{report.safe_filename}]: {w}")

        if not report.passed:
            for e in report.errors:
                logger.warning(f"格式预检失败 [{report.safe_filename}]: {e}")

        logger.info(
            f"格式预检完成: {report.safe_filename}, "
            f"passed={report.passed}, "
            f"declared={report.declared_type}, "
            f"real={report.real_type}"
        )

        return report


# 全局单例
upload_prechecker = UploadPreChecker()
