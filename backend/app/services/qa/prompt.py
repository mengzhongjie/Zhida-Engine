"""
智答引擎（ZhiDa Engine）—— Prompt 模板

支持多种场景的 Prompt 模板：
- 默认问答（群聊/私聊）
- 电商客服（带商品信息）
- 来源引用（附消息来源）
- 回答不了时自动 @ 指定用户
"""

from datetime import datetime
from typing import Optional


class PromptTemplate:
    """
    Prompt 模板管理器

    所有模板均支持变量替换，变量使用 {variable_name} 格式。
    """

    # ================================================================
    # 默认问答模板
    # ================================================================

    DEFAULT_SYSTEM_PROMPT = """你是一个智能问答助手，基于提供的参考内容来回答问题。参考内容可能来自知识库或网络检索。

## 规则
1. 优先根据下方【参考内容】回答，不要编造信息；网络内容需谨慎表述
2. 如果参考内容中没有相关信息，请明确说明不确定性
3. 回答要简洁、准确，优先使用中文
4. 只输出自然语言纯文本，不使用 Markdown 标记；不要使用 #、*、-、``` 等排版语法
5. 如果参考知识中有多个相关片段，请综合整理后给出完整回答
6. 回答中不要提及"参考知识"、"知识库"等内部术语

## 当前时间
{current_time}

## 参考内容
{context}

{conversation_section}

## 用户问题
{question}

请回答："""

    # ================================================================
    # 带来源引用的模板
    # ================================================================

    SOURCE_CITATION_PROMPT = """你是一个智能问答助手，基于提供的参考内容来回答问题。

## 规则
1. 优先根据下方【参考内容】回答，不要编造信息
2. 如果参考内容中没有相关信息，请明确说明不确定性
3. 回答要简洁、准确，优先使用中文，不使用 Markdown 标记
4. 回答末尾附上信息来源（格式：[来源: {source}]）

## 当前时间
{current_time}

## 参考内容
{context}

## 用户问题
{question}

请回答，并在回答末尾附上信息来源："""

    # ================================================================
    # 自动 @ 指定用户的模板（回答不了时）
    # ================================================================

    AUTO_MENTION_TEMPLATE = """抱歉，关于「{question}」这个问题，我暂时无法从知识库中找到准确答案。

已经 @ {mention_users} 来帮你解答，请稍等~ 🙏

{source_info}"""

    # ================================================================
    # 电商客服模板
    # ================================================================

    ECOMMERCE_SYSTEM_PROMPT = """你是一个专业的电商客服助手，基于提供的商品和店铺信息来回答买家问题。

## 规则
1. 仅根据下方【参考知识】中的内容回答，不要编造商品信息
2. 回答要热情、专业，体现服务意识
3. 优先使用中文，语气友好
4. 如果没有相关信息，请引导买家联系人工客服
5. 回答中不要提及"参考知识"、"知识库"等内部术语

## 商品信息
{context}

## 买家问题
{question}

请以客服身份回答："""

    # ================================================================
    # 聊天学习模板（Q&A 提取）
    # ================================================================

    QA_EXTRACTION_PROMPT = """你是一个知识提取助手，需要从聊天记录中提取问答对。

## 规则
1. 判断这条消息是否是一个"问题"（包含疑问、请教、求助等意图）
2. 如果不是问题，返回 {"is_question": false}
3. 如果是问题，提取出问题内容和对应的回答
4. 回答来源：该用户的下一条消息，或群内其他人的回复
5. 忽略闲聊、表情包、纯感叹等非知识性内容

## 聊天记录
{chat_context}

请以 JSON 格式返回：
{{
    "is_question": true/false,
    "question": "提取的问题",
    "answer": "提取的回答",
    "confidence": 0.0-1.0
}}"""

    # ================================================================
    # 构建方法
    # ================================================================

    def build_qa_prompt(
        self,
        question: str,
        context: str,
        source_info: str = "",
        include_sources: bool = False,
        conversation_context: str = "",
    ) -> str:
        """
        构建问答 Prompt

        Args:
            question: 用户问题
            context: 检索到的参考知识
            source_info: 来源信息（可选）
            include_sources: 是否附带来源引用

        Returns:
            完整的 Prompt 文本
        """
        current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")

        # 来源以结构化 sources 字段交给前端展示，正文不要求模型重复生成引用。
        # 保留参数是为了兼容既有调用方。
        conversation_section = (
            f"## 最近对话\n{conversation_context}\n"
            if conversation_context else ""
        )
        return self.DEFAULT_SYSTEM_PROMPT.format(
            current_time=current_time,
            context=context,
            conversation_section=conversation_section,
            question=question,
        )

    def build_ecommerce_prompt(
        self,
        question: str,
        context: str,
    ) -> str:
        """构建电商客服 Prompt"""
        return self.ECOMMERCE_SYSTEM_PROMPT.format(
            context=context,
            question=question,
        )

    def build_auto_mention(
        self,
        question: str,
        mention_users: str,
        source_info: str = "",
        failed_attempt: bool = False,
    ) -> str:
        """
        构建自动 @ 消息

        Args:
            question: 原始问题
            mention_users: 要 @ 的用户名称
            source_info: 部分匹配到的来源信息
            failed_attempt: 是否所有模型都失败

        Returns:
            @ 消息文本
        """
        if failed_attempt:
            return (
                f"抱歉，AI 助手暂时无法提供服务 😢\n\n"
                f"已经 @ {mention_users} 来帮你解答，请稍等~"
            )

        return self.AUTO_MENTION_TEMPLATE.format(
            question=question[:100],
            mention_users=mention_users,
            source_info=f"\n💡 部分相关内容：{source_info}" if source_info else "",
        )

    def build_qa_extraction_prompt(self, chat_context: str) -> str:
        """构建 Q&A 提取 Prompt"""
        return self.QA_EXTRACTION_PROMPT.format(chat_context=chat_context)

    @staticmethod
    def build_context_from_results(
        results: list,
        max_tokens: int = 4000,
    ) -> str:
        """
        将检索结果构建为上下文文本

        Args:
            results: 检索结果列表（IndexResult 或 dict）
            max_tokens: 最大 token 数（粗略估计：1 token ≈ 1.5 字符）

        Returns:
            上下文文本
        """
        max_chars = max_tokens * 1.5

        context_parts = []
        total_chars = 0

        for i, result in enumerate(results):
            text = result.text if hasattr(result, "text") else result.get("text", "")
            source = ""

            # 获取来源信息
            if hasattr(result, "metadata"):
                meta = result.metadata
            else:
                meta = result.get("metadata", {})

            # 来源标签
            if meta.get("section_title"):
                source = f" [来源: {meta['section_title']}]"
            elif meta.get("filename"):
                source = f" [来源: {meta['filename']}]"

            # 构建片段
            part = f"---\n片段 {i+1}{source}:\n{text}"

            if total_chars + len(part) > max_chars:
                break

            context_parts.append(part)
            total_chars += len(part)

        return "\n\n".join(context_parts)


# 全局 Prompt 模板实例
prompt_template = PromptTemplate()
