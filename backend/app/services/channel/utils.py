"""渠道公共工具：把模型输出的 Markdown 降级为纯文本（供 QQ/飞书等渠道发送）。"""
import re


def plain_text(value: str, limit: int = 1900) -> str:
    """移除 Markdown 标记并压缩空行，保留语义；超长截断。

    QQ / 飞书群消息不渲染 Markdown，直接发送会导致原样显示标记符号，
    因此在此统一做降级清洗。
    """
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"```(?:[A-Za-z0-9_+-]+)?\s*\n?", "", text)
    text = text.replace("```", "")
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", r"\1（\2）", text)
    text = re.sub(r"(^|\n)\s{0,3}#{1,6}\s+", r"\1", text)
    text = re.sub(r"(^|\n)\s*>\s?", r"\1", text)
    text = re.sub(r"(^|\n)\s*[-*+]\s+", r"\1• ", text)
    text = re.sub(r"(^|\n)\s*\d+[.)]\s+", r"\1", text)
    text = re.sub(r"(?<!\*)\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    text = re.sub(r"(?<!_)_{1,3}([^_]+)_{1,3}", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"(?m)^\s*[-*_]{3,}\s*$", "", text)
    # 简单表格降级为逐行文本，去掉分隔线与多余竖线。
    text = re.sub(r"(?m)^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$", "", text)
    text = re.sub(r"(?m)^\s*\|\s*", "", text)
    text = re.sub(r"\s*\|\s*(?=\S)", " · ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
