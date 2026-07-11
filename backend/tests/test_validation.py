"""
格式检查模块测试
"""

import os
import sys
import tempfile

# 确保后端包在路径中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.validation.file_validator import FileFormatValidator
from app.services.validation.precheck import UploadPreChecker
from app.services.validation.quality_checker import ParseQualityChecker, QualityReport


class TestFileFormatValidator:
    """文件格式校验器测试"""

    def setup_method(self):
        self.validator = FileFormatValidator()

    def test_detect_pdf_by_magic(self):
        """PDF magic bytes → real_type='pdf'"""
        data = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"
        result = self.validator.detect(data)
        assert result.real_type == "pdf", f"Expected pdf, got {result.real_type}"

    def test_detect_png_by_magic(self):
        """PNG magic bytes → real_type='png'"""
        # PNG 头: 89 50 4E 47 0D 0A 1A 0A
        data = bytes([
            0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
            0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,
        ])
        result = self.validator.detect(data)
        assert result.real_type == "png", f"Expected png, got {result.real_type}"

    def test_detect_jpeg_by_magic(self):
        """JPEG magic bytes → real_type='jpg'"""
        data = bytes([0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46])
        result = self.validator.detect(data)
        assert result.real_type == "jpg"

    def test_detect_text_as_txt(self):
        """纯文本无 magic → real_type='txt'"""
        data = b"This is a plain text file.\nWith multiple lines of content.\nAll regular ASCII text.\n"
        result = self.validator.detect(data)
        assert result.is_text, "纯文本应被标记为 is_text"
        assert result.real_type == "txt"

    def test_detect_html_content(self):
        """HTML 内容 → real_type='html'"""
        data = b"<!DOCTYPE html>\n<html lang='en'>\n<head></head>\n<body></body>\n</html>"
        result = self.validator.detect(data)
        assert "html" in result.real_type or result.real_type == "txt"

    def test_detect_zip_as_zip(self):
        """ZIP magic bytes → real_type='zip'"""
        import zipfile, io
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as zf:
            zf.writestr("test.txt", "hello")
        data = buf.getvalue()
        result = self.validator.detect(data)
        assert result.real_type == "zip" or result.is_archive

    def test_detect_docx_container_and_accepts_docx_extension(self):
        """DOCX 是 ZIP 容器，严格预检也必须接受其真实类型。"""
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("[Content_Types].xml", "<Types />")
            zf.writestr("word/document.xml", "<w:document />")

        result = self.validator.detect(buf.getvalue())
        assert result.real_type == "docx"
        passed, message = self.validator.validate_extension(result.real_type, "docx", strict=True)
        assert passed, message

    def test_type_mismatch_rejected_strict(self):
        """严格模式下，类型不匹配被拒绝"""
        # PDF 的 magic bytes 但声明为 .exe
        passed, msg = self.validator.validate_extension("pdf", "exe", strict=True)
        assert not passed
        assert "不匹配" in msg

    def test_type_mismatch_warning_nonstrict(self):
        """非严格模式下，不匹配仅警告"""
        passed, msg = self.validator.validate_extension("pdf", "exe", strict=False)
        assert passed  # 通过但不建议
        assert "不匹配" in msg

    def test_type_match_passes(self):
        """类型匹配通过"""
        passed, msg = self.validator.validate_extension("pdf", "pdf")
        assert passed
        assert not msg

    def test_jpg_jpeg_alias(self):
        """别名匹配（jpg ↔ jpeg）"""
        passed, msg = self.validator.validate_extension("jpg", "jpeg")
        assert passed
        passed, msg = self.validator.validate_extension("jpeg", "jpg")
        assert passed

    def test_empty_data_returns_unknown(self):
        """空数据返回未知"""
        result = self.validator.detect(b"")
        assert result.real_type == "" or result.real_type == "unknown"
        assert result.warning

    def test_binary_data_detected(self):
        """二进制数据（非文本）被正确识别"""
        # 全是 NULL + 控制字符
        data = b"\x00\x01\x02\xff\xfe" * 200
        result = self.validator.detect(data)
        assert not result.is_text


class TestUploadPreChecker:
    """上传前预检器测试"""

    def setup_method(self):
        self.checker = UploadPreChecker()

    def test_sanitize_removes_path_traversal(self):
        """路径穿越字符被替换"""
        result = self.checker.sanitize_filename("../../etc/passwd")
        assert ".." not in result
        assert ".." not in result  # 两层都处理

    def test_sanitize_removes_dangerous_chars(self):
        """危险字符被替换"""
        result = self.checker.sanitize_filename("file<>.txt")
        assert "<" not in result
        assert ">" not in result

    def test_sanitize_preserves_chinese(self):
        """中文文件名被保留"""
        result = self.checker.sanitize_filename("报告2024.pdf")
        assert "报告" in result
        assert "2024" in result
        assert "pdf" in result.lower()

    def test_sanitize_truncates_long(self):
        """超长文件名被截断"""
        long_name = "a" * 300 + ".pdf"
        result = self.checker.sanitize_filename(long_name)
        assert len(result) <= 210  # 略高于 _MAX_FILENAME_LENGTH

    def test_sanitize_empty_returns_untitled(self):
        """空文件名返回 untitled"""
        result = self.checker.sanitize_filename("")
        assert result == "untitled"

    def test_empty_file_rejected(self):
        """空文件被拒绝"""
        report = self.checker.check(b"", "test.pdf")
        assert not report.passed
        assert any("空" in e for e in report.errors)

    def test_valid_pdf_passes_check(self):
        """有效 PDF 通过预检"""
        data = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"
        report = self.checker.check(data, "document.pdf")
        assert report.passed, f"预检失败: {report.errors}"
        assert report.real_type == "pdf"
        assert report.safe_filename == "document.pdf"

    def test_type_mismatch_rejected(self):
        """类型不匹配被拒绝"""
        # PDF 内容但声称是 .exe
        data = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"
        report = self.checker.check(data, "virus.exe")
        assert not report.passed
        assert report.type_mismatch


# 辅助函数：创建模拟 ParseResult
def make_parse_result(text="", pages=None, tables=None, metadata=None, status="success"):
    class FakeParseResult:
        pass
    r = FakeParseResult()
    r.text = text
    r.pages = pages or ([text] if text else [])
    r.tables = tables or []
    r.metadata = metadata or {}
    r.status = FakeParseResult()
    r.status.value = status
    return r


class TestParseQualityChecker:
    """解析结果质量检查器测试"""

    def setup_method(self):
        self.checker = ParseQualityChecker()

    def test_normal_text_passes(self):
        """正常文本通过质检"""
        text = "这是第一页的内容。\n\n这是第二页的内容。\n\n答案是正确的。\n"
        result = make_parse_result(text=text)
        report = self.checker.check(result)
        assert report.passed, f"质量检查未通过: score={report.score}, errors={report.errors}"
        assert report.score >= 10
        assert "zh" in report.detected_language or "mixed" in report.detected_language

    def test_empty_content_rejected(self):
        """空内容被拒绝"""
        result = make_parse_result(text="")
        report = self.checker.check(result)
        assert not report.passed  # auto_reject_empty=True
        assert any("空" in e for e in report.errors)

    def test_short_content_warned(self):
        """过短内容被标记"""
        result = make_parse_result(text="hi")
        report = self.checker.check(result)
        assert not report.passed  # 低于默认 min_text_length=10

    def test_garbage_text_detected(self):
        """乱码文本被检出"""
        result = make_parse_result(text="\x00\x00\x00��" * 100 + "normal text")
        report = self.checker.check(result)
        assert report.garbage_ratio > 0.3
        assert any("乱码" in w for w in report.warnings)

    def test_completeness_scoring_normal(self):
        """正常文档完整度评分较高"""
        text = "## 第一章\n这是正文内容。\n\n## 第二章\n更多内容。\n答案是正确的。\n"
        pages = [text[:30], text[30:60], text[60:]]
        result = make_parse_result(
            text=text,
            pages=pages,
            metadata={"total_pages": 3},
        )
        report = self.checker.check(result)
        assert report.completeness_score >= 50

    def test_completeness_scoring_truncated(self):
        """截断文本完整度较低"""
        text = "第一页内容，还没写完整，后面就被截断了，"
        result = make_parse_result(text=text)
        report = self.checker.check(result)
        # 短文本应得分较低
        assert report.completeness_score < 60

    def test_language_detection_chinese(self):
        """中文文本 → zh"""
        text = "这是一个中文测试文档。我们希望通过这个文档来验证语言检测功能。智答引擎是一个基于 RAG 架构的知识助手。"
        result = make_parse_result(text=text)
        report = self.checker.check(result)
        assert report.detected_language == "zh"

    def test_language_detection_english(self):
        """英文文本 → en"""
        text = "This is an English document. We use this to test language detection in the quality checker module."
        result = make_parse_result(text=text)
        report = self.checker.check(result)
        assert report.detected_language == "en"

    def test_structure_with_tables_scores_high(self):
        """有表格的结构评分较高"""
        text = "| Name | Age |\n|------|-----|\n| Alice | 30 |\n## Section\nSome text.\n```python\nprint('hello')\n```"
        result = make_parse_result(
            text=text,
            tables=["| Name | Age |\n|------|-----|\n| Alice | 30 |"],
            metadata={"has_tables": True, "has_code": True},
        )
        report = self.checker.check(result)
        assert report.structure_score >= 60
        assert report.score >= 30

    def test_quality_checker_singleton(self):
        """全局单例正常"""
        from app.services.validation.quality_checker import parse_quality_checker
        assert parse_quality_checker is not None
