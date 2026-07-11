"""
智答引擎（ZhiDa Engine）—— 解析结果质量检查

对 DocumentParser 输出的 ParseResult 做多维质量评分：
1. 空文本检测
2. 乱码检测（不可打印字符、替换字符、控制字符）
3. 文本完整度评分（结尾/页码/空白率/密度）
4. 语言检测
5. 结构质量评分（表格/公式/代码/标题层级保全度）

所有评分汇总为 0-100 的综合质量分数，用于判定是否入库。
"""

import os
import re
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from app.services.validation.config import ValidationConfig, get_validation_config


# 控制字符集合（排除正常的 \t \n \r）
_C0_CONTROLS = frozenset(
    chr(i) for i in range(32) if i not in (9, 10, 13)  # \t \n \r
)

# 用于 Unicode 范围推断语言的 CJK 统一表意文字区间
_CJK_RANGES = [
    (0x4E00, 0x9FFF),   # CJK 统一表意文字
    (0x3400, 0x4DBF),   # CJK 扩展 A
    (0x2E80, 0x2EFF),   # CJK 部首补充
    (0x3000, 0x303F),   # CJK 符号和标点
    (0xFF00, 0xFFEF),   # 全角形式
    (0x2F00, 0x2FDF),   # 康熙部首
]
_LATIN_RANGE = (0x0041, 0x007A)  # A-Z a-z

# 乱码模式正则
_REPLACEMENT_CHAR = re.compile(r"�")
_CONTROL_SEQ = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]+")
_BINARY_PATTERN = re.compile(r"[^\x20-\x7e\t\n\r一-鿿]{3,}")


@dataclass
class QualityReport:
    """解析质量报告"""
    score: int = 0                   # 综合质量评分 0-100
    passed: bool = False             # 是否通过最低标准
    text_length: int = 0             # 文本总长度
    garbage_ratio: float = 0.0       # 乱码字符比例 (0-1)
    completeness_score: int = 0      # 文本完整度 (0-100)
    structure_score: int = 0         # 结构完整度 (0-100)
    detected_language: str = ""      # 检测到的语言
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class ParseQualityChecker:
    """解析结果质量检查器

    对 DocumentParser.parse() 返回的 ParseResult 做多维质量评分。
    在切片/索引之前执行，避免垃圾数据入库。
    """

    def __init__(self, config: Optional[ValidationConfig] = None):
        self._config = config or get_validation_config()

    def check(self, parse_result) -> QualityReport:
        """对 ParseResult 执行全面质量检查

        Args:
            parse_result: DocumentParser.parse() 的返回值，需包含
                text, pages, metadata, tables, status 等属性

        Returns:
            QualityReport 包含各维度评分和汇总
        """
        report = QualityReport()
        text = getattr(parse_result, "text", "") or ""
        pages = getattr(parse_result, "pages", []) or []
        tables = getattr(parse_result, "tables", []) or []
        metadata = getattr(parse_result, "metadata", {}) or {}
        status = getattr(parse_result, "status", None)

        report.text_length = len(text)

        # 1. 空内容检测
        self._check_empty(text, metadata, report)

        # 2. 乱码检测
        self._check_garbage(text, report)

        # 3. 文本完整度评分
        report.completeness_score = self._score_completeness(text, pages, metadata)

        # 4. 语言检测
        report.detected_language = self._detect_language(text)

        # 5. 结构质量评分
        report.structure_score = self._score_structure(text, tables, metadata)

        # 6. 综合评分
        report.score = self._calculate_overall(report)

        # 7. 判定是否通过
        report.passed = (
            len(report.errors) == 0
            and report.score >= self._config.min_quality_score
        )

        logger.info(
            f"质量检查: score={report.score}, "
            f"passed={report.passed}, "
            f"lang={report.detected_language}, "
            f"garbage={report.garbage_ratio:.2%}, "
            f"length={report.text_length}"
        )

        return report

    # ================================================================
    # 各维度检查
    # ================================================================

    def _check_empty(self, text: str, metadata: dict, report: QualityReport) -> None:
        """空内容或异常状态检测"""
        # 解析失败直接标记
        if hasattr(text, "status"):
            status = getattr(text, "status", None)
            if status and "fail" in str(status).lower():
                report.errors.append(f"解析状态异常: {status}")
                return

        stripped = text.strip()
        min_len = self._config.min_text_length

        if not stripped:
            report.errors.append("文本内容为空")
        elif len(stripped) < min_len:
            if self._config.auto_reject_empty:
                report.errors.append(
                    f"解析文本过短 ({len(stripped)} 字符 < {min_len})"
                )
            else:
                report.warnings.append(
                    f"解析文本较短 ({len(stripped)} 字符)"
                )

    def _check_garbage(self, text: str, report: QualityReport) -> None:
        """检测乱码文本比例"""
        if not text:
            report.garbage_ratio = 1.0
            return

        # 计数各类乱码信号
        null_count = text.count("\x00")
        replacement_count = len(_REPLACEMENT_CHAR.findall(text))
        control_count = sum(1 for c in text[:10000] if c in _C0_CONTROLS)

        # 二进制模式匹配计数（取前 10000 字符加速）
        binary_run_chars = sum(len(m.group()) for m in _BINARY_PATTERN.finditer(text[:10000]))

        garbage_chars = null_count + replacement_count + control_count + binary_run_chars
        text_len = max(len(text), 1)
        report.garbage_ratio = min(garbage_chars / text_len, 1.0)

        threshold = self._config.garbage_threshold
        if report.garbage_ratio > threshold:
            report.warnings.append(
                f"文本乱码比例过高: {report.garbage_ratio:.1%} > {threshold:.0%}"
            )

    def _score_completeness(self, text: str, pages: list, metadata: dict) -> int:
        """文本完整度评分 (0-100)

        从结尾完整性、页码完整性、空白比例、文本密度四个维度评分。
        """
        if not text.strip():
            return 0

        score = 0
        stripped_text = text.rstrip()

        # 维度 1: 结尾完整性 (25 分)
        # ——完整内容通常以句号/换行/引号结尾
        if stripped_text:
            last_char = stripped_text[-1]
            if last_char in "。！？.!?\n" "」』》" "』" "》" "」" "』":
                score += 25
            elif last_char in "，、；：,;:":
                score += 10  # 逗号结尾可能是截断
            else:
                score += 5  # 简短摘要可能没有句号
        else:
            score += 5

        # 维度 2: 页码完整性 (25 分)
        total_pages = metadata.get("total_pages", metadata.get("total_pages", 0))
        if isinstance(total_pages, (int, float)) and total_pages > 0:
            actual_pages = len(pages) if pages else 1
            page_ratio = actual_pages / max(total_pages, 1)
            if page_ratio >= 0.8:
                score += 25
            elif page_ratio >= 0.5:
                score += 15
            else:
                score += 5
        else:
            # 无页码信息：仅有单页算正常，给一半分
            score += 12

        # 维度 3: 无大段空白 (25 分)
        lines = text.split("\n")
        if lines:
            blank_lines = sum(1 for line in lines if not line.strip())
            blank_ratio = blank_lines / max(len(lines), 1)
            if blank_ratio < 0.05:
                score += 25
            elif blank_ratio < 0.15:
                score += 15
            elif blank_ratio < 0.3:
                score += 5

        # 维度 4: 文本密度 (25 分)
        # — 太短 (<100 字符) 说明解析可能不完整
        length = len(text)
        if length >= 5000:
            score += 25
        elif length >= 1000:
            score += 20
        elif length >= 200:
            score += 15
        elif length >= 50:
            score += 10
        else:
            score += 5

        return min(score, 100)

    def _detect_language(self, text: str) -> str:
        """检测文本的主要语言

        使用 langdetect（已安装），短文本 (<50 字符) 回退到
        Unicode 范围推断。

        Returns:
            语言代码: "zh" / "en" / "ja" / "ko" / "mixed" / "unknown"
        """
        if not text or len(text.strip()) < 20:
            return "unknown"

        sample = text[:2000]

        try:
            from langdetect import detect, DetectorFactory
            DetectorFactory.seed = 0  # 确定性
            lang = detect(sample)
            # 标准化: zh-cn → zh, zh-tw → zh
            return lang.split("-")[0]
        except Exception:
            # langdetect 失败，回退到 Unicode 范围推断
            return self._unicode_range_guess(sample)

    @staticmethod
    def _unicode_range_guess(text: str) -> str:
        """基于 Unicode 范围的语言推断（兜底方案）"""
        if not text:
            return "unknown"

        cjk_count = 0
        latin_count = 0

        for c in text:
            cp = ord(c)
            # CJK 字符
            for start, end in _CJK_RANGES:
                if start <= cp <= end:
                    cjk_count += 1
                    break
            # 拉丁字母
            if 0x0041 <= cp <= 0x007A:
                latin_count += 1

        total = cjk_count + latin_count
        if total == 0:
            return "unknown"
        if cjk_count / total > 0.6:
            return "zh"
        if latin_count / total > 0.6:
            return "en"
        if cjk_count > 0 and latin_count > 0:
            return "mixed"
        return "unknown"

    def _score_structure(self, text: str, tables: list, metadata: dict) -> int:
        """结构质量评分 (0-100)

        检查解析器声明的结构特征是否真在文本中存在。
        """
        if not text.strip():
            return 0

        score = 0

        # 维度 1: 表格对应 (30 分)
        has_tables_meta = metadata.get("has_tables", False)
        has_md_tables = bool(re.search(r"\|[^|]+\|[^|]+\|", text))
        if has_tables_meta:
            if has_md_tables:
                score += 30  # 表声明 + 表存在 = 完美
            elif tables:
                score += 20  # 有 tables 列表但文本中无 Markdown 表
            else:
                score += 0   # 声称有表但哪里都找不到
        else:
            score += 30  # 没有声明表格，不扣分

        # 维度 2: 公式对应 (30 分)
        has_formulas_meta = metadata.get("has_formulas", False)
        has_tex = "$$" in text or ("$" in text and "\\" in text)
        if has_formulas_meta:
            if has_tex:
                score += 30
            else:
                score += 10  # 声明有公式但文本中难以找到
        else:
            score += 30  # 无公式声明，不扣分

        # 维度 3: 代码块对应 (20 分)
        has_code_meta = metadata.get("has_code", False)
        has_fences = "```" in text
        if has_code_meta:
            if has_fences:
                score += 20
            else:
                score += 5  # 声明有代码但无明显围栏
        else:
            score += 20

        # 维度 4: 标题层级 (20 分)
        heading_count = sum(
            1 for line in text.split("\n")
            if line.startswith("##") or line.startswith("# ")
        )
        if heading_count >= 5:
            score += 20
        elif heading_count >= 2:
            score += 15
        elif heading_count >= 1:
            score += 10

        return min(score, 100)

    @staticmethod
    def _calculate_overall(report: QualityReport) -> int:
        """综合评分"""
        score = (
            report.completeness_score * 0.5
            + report.structure_score * 0.3
            + max(0, (1.0 - report.garbage_ratio)) * 20  # 乱码越低越好
        )
        return round(min(score, 100))


# 全局单例
parse_quality_checker = ParseQualityChecker()
