"""
智答引擎（ZhiDa Engine）—— 文件格式校验器

基于 filetype 库的 magic bytes 检测，验证文件的真实类型，
防止通过扩展名伪装绕过上传校验。

支持的格式：
- PDF: magic bytes %PDF
- DOCX/XLSX/PPTX: ZIP 容器 + 内部结构识别
- PNG/JPEG/GIF/BMP/WEBP/TIFF: 图片 magic bytes
- EPUB: ZIP 容器 + mimetype 条目
- HTML: <html 或 DOCTYPE 文本
- TXT/MD/CSV/JSON: 纯文本试探检测
"""

import os
import zipfile
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

try:
    import filetype
    HAS_FILETYPE = True
except ImportError:
    HAS_FILETYPE = False


# ZIP 格式的内部识别标记
_ZIP_FORMAT_MARKERS: dict[str, list[str]] = {
    "docx": [
        "[Content_Types].xml",
        "word/document.xml",
        "word/",
    ],
    "xlsx": [
        "[Content_Types].xml",
        "xl/workbook.xml",
        "xl/",
    ],
    "pptx": [
        "[Content_Types].xml",
        "ppt/presentation.xml",
        "ppt/",
    ],
}

# 纯文本格式的关键字标记（用于无 magic 的文件）
_TEXT_FORMAT_HINTS: dict[str, list[bytes]] = {
    # 结构化标记优先（防止 `{` 或 `[` 被误判为 md）
    "json": [b"{"],                                 # {"key": ...
    "html": [b"<html", b"<!DOCTYPE html", b"<!doctype html"],
    "xml": [b"<?xml", b"<xml"],                      # <?xml version=
    "yaml": [b"---\n", b":\n"],                     # ---\n
    # Markdown 标记放在结构化格式之后
    "md": [b"# ", b"## ", b"### ", b"```", b"](", b"!("],  # 用 [text](url) 的 ]( 代替宽泛的 [
    "sql": [b"CREATE", b"SELECT", b"INSERT", b"ALTER", b"DROP"],
}

# 最低字节数用于检测（PDF 头 5 字节，ZIP 头 4 字节，图片头通常 8 字节）
_MIN_DETECT_BYTES = 512


@dataclass
class FormatValidationResult:
    """文件格式校验结果"""
    real_type: str = ""           # magic bytes 检测到的真实类型
    declared_type: str = ""       # 扩展名声称的类型
    type_mismatch: bool = False   # 类型是否不匹配
    is_archive: bool = False      # 是否为 ZIP 等归档格式
    is_text: bool = False         # 是否判定为文本文件
    detected_extension: str = ""  # filetype.guess 的扩展名结果
    warning: str = ""             # 警告信息


class FileFormatValidator:
    """文件格式校验器 —— magic bytes → 真实类型映射"""

    @staticmethod
    def detect(file_bytes: bytes) -> FormatValidationResult:
        """检测文件的真实类型

        Args:
            file_bytes: 文件二进制内容（至少 512 字节）

        Returns:
            FormatValidationResult 包含检测结果
        """
        result = FormatValidationResult()

        if not file_bytes:
            result.warning = "文件内容为空"
            return result

        # 1. 使用 filetype 库检测
        ft_result = None
        if HAS_FILETYPE:
            try:
                ft_result = filetype.guess(file_bytes)
            except Exception:
                pass

        if ft_result:
            result.detected_extension = ft_result.extension
            result.real_type = ft_result.extension
            result.is_archive = ft_result.mime and "zip" in ft_result.mime
            result.is_text = "text" in (ft_result.mime or "")

        # 2. ZIP 容器深度识别（DOCX/XLSX/PPTX/EPUB）。
        # 不能只依赖可选的 filetype 包：缺少该包时，标准 DOCX 仍应可上传。
        if (
            result.real_type == "zip"
            or result.real_type == "application/zip"
            or file_bytes.startswith(b"PK\x03\x04")
        ):
            result = FileFormatValidator._identify_zip_type(file_bytes)

        # 3. 纯文本试探（filetype 无法识别时为 txt，进一步辨别）
        if not result.real_type or result.real_type == "unknown":
            result.real_type, result.is_text = FileFormatValidator._detect_text_type(file_bytes)

        # 4. 无匹配的未知文件
        if not result.real_type:
            result.real_type = "unknown"
            result.warning = "无法识别文件格式"

        return result

    @staticmethod
    def _identify_zip_type(file_bytes: bytes) -> FormatValidationResult:
        """识别 ZIP 容器内部的文档类型

        遍历 ZIP 条目匹配已知结构标记。
        """
        result = FormatValidationResult()
        result.is_archive = True
        result.real_type = "zip"  # 默认

        try:
            with zipfile.ZipFile(io.BytesIO(file_bytes)) as zf:
                names = [n.rstrip("/") for n in zf.namelist()]

                # 检查 EPUB (mimetype 条目)
                if "mimetype" in names:
                    try:
                        mt = zf.read("mimetype").decode("utf-8", errors="replace").strip()
                        if "epub" in mt.lower():
                            result.real_type = "epub"
                            return result
                    except Exception:
                        pass

                # 检查 Office 格式
                for fmt, markers in _ZIP_FORMAT_MARKERS.items():
                    # 至少匹配其中两个标记才认定
                    matches = sum(1 for m in markers if any(m in n for n in names))
                    if matches >= 2:
                        result.real_type = fmt
                        return result

        except (zipfile.BadZipFile, Exception):
            result.warning = "ZIP 文件可能已损坏"

        return result

    @staticmethod
    def _detect_text_type(file_bytes: bytes) -> tuple[str, bool]:
        """检测纯文本文件的子类型

        先用可打印字符比例判断是否为文本，
        再通过内容特征进一步识别 HTML/JSON/Markdown 等。

        Returns:
            (type_name: str, is_text: bool)
        """
        # 检查文本字符比例
        # 计数范围：可打印 ASCII (32-126) + 控制符 (9,10,13) + UTF-8 多字节 (128-255)
        text_chars = sum(1 for b in file_bytes[:4096] if 32 <= b <= 126 or b in (9, 10, 13) or b >= 128)
        total_checked = min(len(file_bytes), 4096)
        text_ratio = text_chars / max(total_checked, 1)

        # 文本比例低 → 尝试 UTF-8 解码验证是否为纯文本
        if text_ratio < 0.6:
            try:
                file_bytes[:1024].decode("utf-8")
                # UTF-8 解码成功，是文本（可能是中文/多语言）
                text_ratio = 1.0
            except (UnicodeDecodeError, UnicodeError):
                return "binary", False

        # 检查 BOM 标记
        if file_bytes[:3] == b"\xef\xbb\xbf":
            pass  # UTF-8 BOM，维持文本判定

        # CSV 检测：至少两行包含逗号
        try:
            text_sample = file_bytes[:2048].decode("utf-8", errors="replace")
            lines_with_commas = sum(1 for line in text_sample.split("\n") if line.count(",") >= 2)
            if lines_with_commas >= 2:
                return "csv", True
        except Exception:
            pass

        # 按内容特征匹配子类型
        header = file_bytes[:1024].lower()
        for fmt, hints in _TEXT_FORMAT_HINTS.items():
            for hint in hints:
                if hint.lower() in header:
                    return fmt, True

        # 默认判定为纯文本
        return "txt", True

    @staticmethod
    def validate_extension(
        real_type: str,
        declared_ext: str,
        strict: bool = True,
    ) -> tuple[bool, str]:
        """对比真实类型和扩展名是否匹配

        Args:
            real_type: magic bytes 检测到的类型
            declared_ext: 文件扩展名（不含点）
            strict: 严格模式（true=不匹配时拒绝，false=仅警告）

        Returns:
            (passed: bool, message: str)
        """
        declared_ext = declared_ext.lower().lstrip(".").strip()

        if not real_type or real_type == "unknown":
            return (not strict, f"无法检测文件真实类型（声明为 .{declared_ext}）")

        # txt/md/csv 的 magic 检测可能不准确，宽松处理
        if declared_ext in {"txt", "md", "csv", "json", "xml", "yaml", "html", "htm", "log"}:
            if real_type == "txt" or real_type == declared_ext:
                return True, ""
            # HTML/XML 也有 magic-like 检测
            if declared_ext == "html" and real_type == "htm":
                return True, ""
            if declared_ext == "htm" and real_type == "html":
                return True, ""

        # 精确匹配
        if real_type == declared_ext:
            return True, ""

        # ZIP 衍生格式（docx/xlsx/pptx/epub 都是 ZIP）
        if real_type in _ZIP_FORMAT_MARKERS and declared_ext in _ZIP_FORMAT_MARKERS:
            # 不同 ZIP 类型之间算不匹配
            pass

        # 某些已知别名或特殊情况
        if (real_type, declared_ext) in {
            ("jpg", "jpeg"), ("jpeg", "jpg"),
            ("tif", "tiff"), ("tiff", "tif"),
            ("htm", "html"), ("html", "htm"),
        }:
            return True, ""

        # 不匹配
        if strict:
            return (
                False,
                f"文件类型不匹配: 扩展名声称 .{declared_ext}，"
                f"实际检测为 {real_type}",
            )

        return (
            True,
            f"文件类型不匹配（仅警告）: 扩展名声称 .{declared_ext}，"
            f"实际检测为 {real_type}",
        )


# 全局单例
file_format_validator = FileFormatValidator()
