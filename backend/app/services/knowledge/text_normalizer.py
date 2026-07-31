"""检索与入库共用的保守文本归一化。"""

import unicodedata


def normalize_text(text: str) -> str:
    """统一 Unicode 兼容字符和换行，不破坏代码及标点语义。"""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    return normalized.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
