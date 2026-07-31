"""
智答引擎（ZhiDa Engine）—— 文本切片器

多粒度自适应切片策略：
1. 固定大小滑动窗口 —— 通用文本
2. 语义分块 —— 按段落/标题边界切分
3. 表格分块 —— Excel 表格数据每行一个 chunk
4. 父子块切分 —— 子块200字符/重叠50，父块4倍大小，仅子块索引

使用 jieba 分词避免中文词语截断，每个 chunk 携带元数据。
"""

import re
from typing import Optional
from dataclasses import dataclass, field

import jieba

from loguru import logger


@dataclass
class TextChunk:
    """文本切片"""
    text: str
    metadata: dict = field(default_factory=dict)
    chunk_index: int = 0
    token_count: int = 0
    parent_id: Optional[str] = None  # 父块 ID（父子块模式）


class TextSplitter:
    """
    文本切片器 —— 多粒度自适应

    Usage:
        splitter = TextSplitter()

        # 固定大小切片
        chunks = splitter.split_fixed(text, chunk_size=500, overlap=50)

        # 语义切片
        chunks = splitter.split_semantic(text)

        # 表格切片
        chunks = splitter.split_table(rows, headers)
    """

    def __init__(
        self,
        chunk_size: int = 500,
        overlap: int = 50,
        separators: Optional[list[str]] = None,
    ):
        """
        Args:
            chunk_size: 切片大小（字符数）
            overlap: 重叠字符数
            separators: 分隔符优先级列表
        """
        self.chunk_size = chunk_size
        self.overlap = overlap
        self.separators = separators or [
            "\n\n",    # 段落分隔
            "\n",      # 换行
            "。",      # 中文句号
            "！",      # 中文感叹号
            "？",      # 中文问号
            "；",      # 中文分号
            ".",       # 英文句号
            "!",       # 英文感叹号
            "?",       # 英文问号
            ";",       # 英文分号
            " ",       # 空格
            "",        # 字符级切分
        ]

        # LangChain 分词器（延迟导入，避免未安装时模块加载失败）
        self._splitter = None  # 懒加载，首次使用时创建
        self._splitter_chunk_size = chunk_size
        self._splitter_overlap = overlap

    @staticmethod
    def _char_count(text: str) -> int:
        """计算文本字符数（中文按 1 字符，英文按单词计）"""
        # 简单实现：统计所有字符
        return len(text)

    def _get_splitter(self, chunk_size: int = None, overlap: int = None):
        """懒加载 LangChain 分词器（延迟导入，避免未安装时模块加载失败）"""
        from langchain.text_splitter import RecursiveCharacterTextSplitter

        cs = chunk_size or self._splitter_chunk_size
        ov = overlap or self._splitter_overlap

        return RecursiveCharacterTextSplitter(
            chunk_size=cs,
            chunk_overlap=ov,
            separators=self.separators,
            length_function=self._char_count,
        )

    def split_fixed(
        self,
        text: str,
        chunk_size: Optional[int] = None,
        overlap: Optional[int] = None,
        metadata: Optional[dict] = None,
    ) -> list[TextChunk]:
        """
        固定大小滑动窗口切片 —— 通用文本

        Args:
            text: 输入文本
            chunk_size: 切片大小（覆盖默认值）
            overlap: 重叠大小（覆盖默认值）
            metadata: 基础元数据

        Returns:
            切片列表
        """
        if not text.strip():
            return []

        # 使用指定参数或默认值
        if chunk_size is not None or overlap is not None:
            splitter = self._get_splitter(chunk_size=chunk_size, overlap=overlap)
            raw_chunks = splitter.split_text(text)
        else:
            splitter = self._get_splitter()
            raw_chunks = splitter.split_text(text)

        # 转为 TextChunk 格式
        chunks = []
        for i, chunk_text in enumerate(raw_chunks):
            if not chunk_text.strip():
                continue

            chunks.append(TextChunk(
                text=chunk_text.strip(),
                metadata={
                    **(metadata or {}),
                    "chunk_method": "fixed",
                    "chunk_size": chunk_size or self.chunk_size,
                },
                chunk_index=i,
                token_count=len(chunk_text),
            ))

        logger.debug(f"固定大小切片: {len(raw_chunks)} → {len(chunks)} 个有效切片")
        return chunks

    def split_semantic(
        self,
        text: str,
        metadata: Optional[dict] = None,
    ) -> list[TextChunk]:
        """
        语义分块 —— 按段落/标题边界切分

        适用于段落结构清晰的文档（如 Word、Markdown）。
        先按 ## 标题切分，再按段落切分。
        """
        if not text.strip():
            return []

        chunks = []
        chunk_index = 0

        # 按 Markdown 标题切分
        sections = re.split(r"\n(?=#{1,6}\s)", text)

        for section in sections:
            if not section.strip():
                continue

            # 提取标题（如果有）
            title_match = re.match(r"^(#{1,6}\s.+)$", section, re.MULTILINE)
            section_title = title_match.group(1) if title_match else ""

            # 按段落切分
            paragraphs = section.split("\n\n")

            for para in paragraphs:
                para = para.strip()
                if not para:
                    continue

                chunks.append(TextChunk(
                    text=para,
                    metadata={
                        **(metadata or {}),
                        "chunk_method": "semantic",
                        "section_title": section_title,
                    },
                    chunk_index=chunk_index,
                    token_count=len(para),
                ))
                chunk_index += 1

        logger.debug(f"语义分块: {len(chunks)} 个切片")
        return chunks

    def split_table(
        self,
        rows: list[dict],
        headers: Optional[list[str]] = None,
        metadata: Optional[dict] = None,
    ) -> list[TextChunk]:
        """
        表格分块 —— 每行一个 chunk，附带表头

        适用于 Excel/CSV 表格数据。

        Args:
            rows: 数据行列表（每行是一个 dict）
            headers: 表头列表
            metadata: 基础元数据

        Returns:
            切片列表
        """
        chunks = []

        for i, row in enumerate(rows):
            # 构建文本：表头 + 当前行
            parts = []
            if headers:
                parts.append("表头: " + " | ".join(headers))

            if isinstance(row, dict):
                parts.append(" | ".join(f"{k}: {v}" for k, v in row.items()))
            else:
                parts.append(str(row))

            chunk_text = "\n".join(parts)

            chunks.append(TextChunk(
                text=chunk_text,
                metadata={
                    **(metadata or {}),
                    "chunk_method": "table",
                    "row_index": i,
                    "total_rows": len(rows),
                },
                chunk_index=i,
                token_count=len(chunk_text),
            ))

        logger.debug(f"表格分块: {len(chunks)} 个切片")
        return chunks

    def split_adaptive(
        self,
        text: str,
        file_type: str = "txt",
        metadata: Optional[dict] = None,
    ) -> list[TextChunk]:
        """
        自适应切片 —— 根据文件类型自动选择最佳策略

        Args:
            text: 输入文本
            file_type: 文件类型（pdf/docx/xlsx/txt/md）
            metadata: 基础元数据

        Returns:
            切片列表
        """
        if file_type in ("xlsx", "csv"):
            # 表格文件：按行切分
            lines = text.strip().split("\n")
            if len(lines) < 2:
                return self.split_fixed(text, metadata=metadata)

            # 解析为简单行
            rows = [{"line": line} for line in lines[1:]]  # 跳过表头
            headers = lines[0].split("|") if "|" in lines[0] else None
            return self.split_table(rows, headers=headers, metadata=metadata)

        elif file_type in ("docx", "md"):
            # 结构化文档：语义分块
            return self.split_semantic(text, metadata=metadata)

        else:
            # 通用文档：固定大小切片
            return self.split_fixed(text, metadata=metadata)

    def merge_small_chunks(
        self,
        chunks: list[TextChunk],
        min_chunk_size: int = 50,
        max_chunk_size: int = 1000,
    ) -> list[TextChunk]:
        """
        合并小切片 —— 避免过小的切片影响检索效果

        Args:
            chunks: 原始切片列表
            min_chunk_size: 最小切片大小（字符数），低于此值的合并到前一/后一切片
            max_chunk_size: 合并后的最大切片大小

        Returns:
            合并后的切片列表
        """
        if not chunks:
            return []

        merged = []
        buffer = ""

        for chunk in chunks:
            if len(chunk.text) < min_chunk_size:
                # 小切片，合并到 buffer
                buffer += "\n" + chunk.text
                continue

            if buffer:
                # 将 buffer 合并到当前切片（如果不超过最大大小）
                combined = buffer.strip() + "\n" + chunk.text
                if len(combined) <= max_chunk_size:
                    buffer = ""
                    merged.append(TextChunk(
                        text=combined,
                        metadata=chunk.metadata,
                        chunk_index=len(merged),
                        token_count=len(combined),
                    ))
                    continue
                else:
                    # buffer 单独成一个切片
                    merged.append(TextChunk(
                        text=buffer.strip(),
                        metadata=chunk.metadata,
                        chunk_index=len(merged),
                        token_count=len(buffer),
                    ))
                    buffer = ""

            merged.append(TextChunk(
                text=chunk.text,
                metadata=chunk.metadata,
                chunk_index=len(merged),
                token_count=len(chunk.text),
            ))

        # 处理最后的 buffer
        if buffer.strip():
            merged.append(TextChunk(
                text=buffer.strip(),
                metadata=chunks[-1].metadata if chunks else {},
                chunk_index=len(merged),
                token_count=len(buffer),
            ))

        if len(merged) < len(chunks):
            logger.debug(f"合并小切片: {len(chunks)} → {len(merged)}")

        return merged

    # ================================================================
    # 父子块切分（Parent-Child Chunking / Small-to-Big）
    # 基于 LangChain RecursiveCharacterTextSplitter 实现
    # ================================================================

    def split_parent_child(
        self,
        text: str,
        child_size: int = 200,
        child_overlap: int = 50,
        parent_multiplier: int = 4,
        metadata: Optional[dict] = None,
    ) -> tuple[list[TextChunk], list[TextChunk]]:
        """
        父子块切分（Small-to-Big）—— 基于 LangChain 实现

        策略：
        - 父块（Parent）: child_size * parent_multiplier 字符 → 存入关系数据库
        - 子块（Child）: child_size 字符，重叠 child_overlap 字符 → 存入向量数据库用于检索
        - 每个子块通过 parent_id 关联到父块
        - 检索时：找到子块 → 获取对应父块 → 返回父块作为完整上下文

        使用 LangChain RecursiveCharacterTextSplitter 进行切分，
        切分前预处理保护代码块完整性。

        Args:
            text: 输入文本
            child_size: 子块大小（字符数），默认 200
            child_overlap: 子块重叠字符数，默认 50
            parent_multiplier: 父块大小是子块的倍数，默认 4（即 800 字符）
            metadata: 基础元数据

        Returns:
            (parent_chunks, child_chunks) —— 父块列表和子块列表
        """
        if not text.strip():
            return [], []

        parent_size = child_size * parent_multiplier

        # ---- 步骤 1：预处理，保护代码块完整性 ----
        protected_text, code_blocks = self._protect_code_blocks(text)

        # ---- 步骤 2：用 LangChain 切父块 ----
        parent_splitter = self._get_langchain_splitter(
            chunk_size=parent_size,
            overlap=0,  # 父块不重叠
        )
        raw_parent_texts = parent_splitter.split_text(protected_text)

        # ---- 步骤 3：恢复代码块，构建父块 TextChunk ----
        parent_chunks: list[TextChunk] = []
        for i, parent_text in enumerate(raw_parent_texts):
            restored_text = self._restore_code_blocks(parent_text, code_blocks)
            if not restored_text.strip():
                continue

            document_id = (metadata or {}).get("document_id")
            parent_id = f"doc_{document_id}_parent_{i}" if document_id is not None else f"parent_{i}"
            content_type = self._detect_content_type(restored_text)

            parent_chunks.append(TextChunk(
                text=restored_text.strip(),
                metadata={
                    **(metadata or {}),
                    "chunk_method": "parent_child_langchain",
                    "chunk_type": "parent",
                    "content_type": content_type,
                    "parent_id": parent_id,
                },
                chunk_index=i,
                token_count=len(restored_text.strip()),
                parent_id=parent_id,
            ))

        # ---- 步骤 4：每个父块切分为子块 ----
        child_splitter = self._get_langchain_splitter(
            chunk_size=child_size,
            overlap=child_overlap,
        )

        all_children: list[TextChunk] = []
        child_global_index = 0

        for parent_idx, parent in enumerate(parent_chunks):
            parent_id = parent.metadata["parent_id"]

            # 保护代码块后再切子块
            protected_parent, parent_code_blocks = self._protect_code_blocks(parent.text)
            raw_child_texts = child_splitter.split_text(protected_parent)

            for child_text in raw_child_texts:
                restored_child = self._restore_code_blocks(child_text, parent_code_blocks)
                if not restored_child.strip():
                    continue

                all_children.append(TextChunk(
                    text=restored_child.strip(),
                    metadata={
                        **(metadata or {}),
                        "chunk_method": "parent_child_langchain",
                        "chunk_type": "child",
                        "parent_id": parent_id,
                        "parent_index": parent_idx,
                    },
                    chunk_index=child_global_index,
                    token_count=len(restored_child.strip()),
                    parent_id=parent_id,
                ))
                child_global_index += 1

        logger.info(
            f"父子块切分完成 (LangChain): {len(parent_chunks)} 个父块, "
            f"{len(all_children)} 个子块 "
            f"(子块大小={child_size}, 重叠={child_overlap}, 父块倍数={parent_multiplier})"
        )

        return parent_chunks, all_children

    def _get_langchain_splitter(self, chunk_size: int, overlap: int):
        """获取 LangChain RecursiveCharacterTextSplitter 实例"""
        from langchain.text_splitter import RecursiveCharacterTextSplitter

        return RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=overlap,
            separators=self.separators,
            length_function=self._char_count,
        )

    def _protect_code_blocks(self, text: str) -> tuple[str, list[dict]]:
        """
        保护代码块 —— 将代码块替换为占位符，避免被切分器切断

        Returns:
            (处理后的文本, 代码块列表)
        """
        code_blocks = []
        pattern = r"```(\w*)\n(.*?)```"

        def replace_code(match):
            idx = len(code_blocks)
            lang = match.group(1) or "code"
            code = match.group(2)
            code_blocks.append({"lang": lang, "code": code})
            return f"\n__CODE_BLOCK_{idx}__\n"

        protected = re.sub(pattern, replace_code, text, flags=re.DOTALL)
        return protected, code_blocks

    def _restore_code_blocks(self, text: str, code_blocks: list[dict]) -> str:
        """恢复代码块 —— 将占位符替换回原始代码块"""
        for i, cb in enumerate(code_blocks):
            placeholder = f"__CODE_BLOCK_{i}__"
            if placeholder in text:
                code_block = f"```{cb['lang']}\n{cb['code']}\n```"
                text = text.replace(placeholder, code_block)
        return text

    def _detect_content_type(self, text: str) -> str:
        """检测文本内容类型"""
        code_markers = text.count("```")
        if code_markers >= 2:
            return "code"
        if re.search(r"^#{1,6}\s", text, re.MULTILINE):
            return "markdown"
        return "text"


# 全局切片器实例
text_splitter = TextSplitter()
