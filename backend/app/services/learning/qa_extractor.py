"""
智答引擎（ZhiDa Engine）—— Q&A 对提取器

从聊天记录中自动提取问答对，核心策略：
1. 先识别问题（是否为疑问/求助意图）
2. 等待回答（该用户下一条消息或群内回复）
3. 质量过滤（太短/纯表情/重复内容不学）
4. 向量化入库

模块开关：settings.ENABLE_AUTO_LEARNING
"""

import json
import re
import hashlib
import time
from typing import Optional
from dataclasses import dataclass, field
from enum import Enum

from loguru import logger

from app.core.config import settings
from app.services.qa.prompt import prompt_template
from app.services.llm.gateway import llm_gateway


class QuestionType(str, Enum):
    """问题类型"""
    QUESTION = "question"     # 明确的疑问句
    HELP = "help"             # 求助/请教
    COMMAND = "command"       # 指令（如"帮我查一下"）
    UNKNOWN = "unknown"       # 未识别


@dataclass
class ChatMessage:
    """聊天消息"""
    message_id: str
    chat_id: str            # 群聊/私聊 ID
    user_id: str            # 发送者 ID
    user_name: str          # 发送者名称
    content: str            # 消息内容
    timestamp: float        # 时间戳
    is_group: bool = True   # 是否为群聊
    reply_to: Optional[str] = None  # 回复的消息 ID


@dataclass
class QAPair:
    """提取的问答对"""
    question: str
    answer: str
    source_chat_id: str
    source_user_id: str      # 提问者
    answer_user_id: str      # 回答者
    confidence: float = 0.0  # 置信度（0-1）
    quality_score: float = 0.0  # 质量评分
    question_hash: str = ""  # 问题哈希（用于去重）


class QuestionDetector:
    """
    问题识别器 —— 判断消息是否为"问题"

    使用规则 + LLM 双重识别：
    1. 规则快速过滤（问号、疑问词、求助关键词）
    2. LLM 精确判断（可选，用于难判断的边缘情况）
    """

    # 疑问词列表
    QUESTION_WORDS = [
        "什么", "怎么", "如何", "为什么", "为啥", "哪", "谁", "何时",
        "多少", "多久", "几点", "几时", "可否", "能否", "是否", "可以",
        "能不能", "行不行", "对吗", "是吗", "怎么样", "咋样", "咋办",
        "怎么办", "怎么弄", "怎么搞", "怎么做", "怎么用", "怎么设置",
        "how", "what", "why", "when", "where", "which", "who",
    ]

    # 求助关键词
    HELP_KEYWORDS = [
        "请问", "请教", "求助", "帮忙", "帮我看", "帮我查", "帮我找",
        "有没有", "在吗", "问一下", "问个", "想问", "咨询", "了解",
        "推荐", "建议", "怎么选择", "选哪个", "区别",
    ]

    # 问号
    QUESTION_MARKS = ["？", "?", "❓", "⁉️"]

    def is_question(self, message: ChatMessage) -> tuple[bool, QuestionType, float]:
        """
        判断消息是否为问题

        Returns:
            (is_question, question_type, confidence)
        """
        content = message.content.strip()

        if not content:
            return False, QuestionType.UNKNOWN, 0.0

        # 规则 1: 包含问号
        if any(mark in content for mark in self.QUESTION_MARKS):
            return True, QuestionType.QUESTION, 0.9

        # 规则 2: 包含疑问词
        for word in self.QUESTION_WORDS:
            if word in content:
                return True, QuestionType.QUESTION, 0.8

        # 规则 3: 包含求助关键词
        for word in self.HELP_KEYWORDS:
            if word in content:
                return True, QuestionType.HELP, 0.7

        # 规则 4: 排除明显非问题
        # 纯表情/图片/文件
        if self._is_non_question(content):
            return False, QuestionType.UNKNOWN, 0.0

        # 默认不是问题
        return False, QuestionType.UNKNOWN, 0.0

    def _is_non_question(self, content: str) -> bool:
        """判断是否为明显非问题内容"""
        # 纯表情
        if re.match(r'^[\U0001F000-\U0001FFFF\u2600-\u27BF\uFE00-\uFEFF\s]+$', content):
            return True

        # 纯数字/符号
        if re.match(r'^[\d\s\.,;:!！。，；：、…]+$', content):
            return True

        # 超短消息（< 3 字）
        if len(content) < 3:
            return True

        return False

    async def is_question_with_llm(self, message: ChatMessage) -> tuple[bool, float]:
        """
        使用 LLM 精确判断是否为问题（用于规则不确定的边缘情况）

        Returns:
            (is_question, confidence)
        """
        try:
            prompt = f"""判断以下消息是否是一个"问题"（包含疑问、请教、求助等意图）。

消息内容：{message.content}

请只回复 JSON：{{"is_question": true/false, "confidence": 0.0-1.0}}"""

            response = await llm_gateway.chat(
                prompt=prompt,
                temperature=0.0,
                max_tokens=50,
            )

            result = json.loads(response.strip())
            return result.get("is_question", False), result.get("confidence", 0.0)

        except Exception as e:
            logger.warning(f"LLM 问题识别失败: {e}")
            return False, 0.0


class QualityFilter:
    """
    质量过滤器 —— 过滤低质量的问答对

    过滤规则：
    1. 回答太短（< 5 字）
    2. 纯表情/符号回答
    3. 重复内容（与已有 Q&A 对相似度过高）
    4. 包含敏感词
    """

    MIN_ANSWER_LENGTH = 5       # 最小回答长度
    MIN_QUESTION_LENGTH = 3     # 最小问题长度

    # 无效回答模式
    INVALID_PATTERNS = [
        r"^[😂😅🤣❤️👍🙏💪🔥🎉😊]+$",  # 纯表情
        r"^[\.。！!？?]+$",             # 纯标点
        r"^[哈哈呵呵嘿嘿嘻嘻]+$",         # 纯笑声
        r"^[啊哦嗯哎唉哟]+$",             # 纯语气词
    ]

    def filter(self, qa_pair: QAPair) -> tuple[bool, str]:
        """
        过滤问答对

        Returns:
            (is_valid, reason)
        """
        # 问题太短
        if len(qa_pair.question) < self.MIN_QUESTION_LENGTH:
            return False, "问题太短"

        # 回答太短
        if len(qa_pair.answer) < self.MIN_ANSWER_LENGTH:
            return False, "回答太短"

        # 纯表情/符号
        for pattern in self.INVALID_PATTERNS:
            if re.match(pattern, qa_pair.answer):
                return False, "无效回答内容"

        # 问题和回答相同（问答循环）
        if qa_pair.question.strip() == qa_pair.answer.strip():
            return False, "问答内容相同"

        # 置信度太低
        if qa_pair.confidence < 0.5:
            return False, "置信度过低"

        return True, "ok"


class QAExtractor:
    """
    Q&A 对提取器 —— 从聊天记录中自动提取知识

    核心流程：
    1. 问题识别（规则 + LLM）
    2. 等待回答（同用户下一条消息 / 群内下一条消息）
    3. 质量过滤
    4. 去重
    5. 入库

    Usage:
        extractor = QAExtractor()

        # 处理消息流
        result = await extractor.process_message(message)
        if result:
            await save_qa_pair(result)
    """

    def __init__(self):
        self._detector = QuestionDetector()
        self._quality_filter = QualityFilter()
        # 待回答队列：chat_id → 等待回答的问题
        self._pending_questions: dict[str, ChatMessage] = {}
        # 已提取的问答对哈希（去重）
        self._known_qa_hashes: set[str] = set()

    async def process_message(self, message: ChatMessage) -> Optional[QAPair]:
        """
        处理一条聊天消息 —— 返回提取到的问答对

        如果模块开关关闭，直接返回 None。

        Args:
            message: 聊天消息

        Returns:
            提取到的 QAPair，或 None
        """
        if not settings.ENABLE_AUTO_LEARNING:
            return None

        chat_id = message.chat_id

        # 检查是否有等待回答的问题
        if chat_id in self._pending_questions:
            pending = self._pending_questions.pop(chat_id)

            # 提取问答对
            qa_pair = QAPair(
                question=pending.content,
                answer=message.content,
                source_chat_id=chat_id,
                source_user_id=pending.user_id,
                answer_user_id=message.user_id,
                confidence=0.8,
                question_hash=self._hash_question(pending.content),
            )

            # 质量过滤
            is_valid, reason = self._quality_filter.filter(qa_pair)
            if not is_valid:
                logger.debug(f"Q&A 对质量不合格: {reason}")
                return None

            # 去重
            if qa_pair.question_hash in self._known_qa_hashes:
                logger.debug("Q&A 对重复，跳过")
                return None

            self._known_qa_hashes.add(qa_pair.question_hash)
            qa_pair.quality_score = self._calculate_quality(qa_pair)

            logger.info(f"提取 Q&A 对: {qa_pair.question[:50]}... → {qa_pair.answer[:50]}...")
            return qa_pair

        # 判断当前消息是否为问题
        is_q, q_type, confidence = self._detector.is_question(message)

        if is_q and confidence >= 0.7:
            # 加入待回答队列
            self._pending_questions[chat_id] = message
            logger.debug(f"识别到问题: {message.content[:50]}... (置信度={confidence})")

        return None

    async def extract_from_history(
        self,
        messages: list[ChatMessage],
    ) -> list[QAPair]:
        """
        从历史消息中批量提取问答对

        Args:
            messages: 按时间排序的消息列表

        Returns:
            提取到的问答对列表
        """
        qa_pairs = []

        for msg in messages:
            result = await self.process_message(msg)
            if result:
                qa_pairs.append(result)

        logger.info(f"从 {len(messages)} 条历史消息中提取 {len(qa_pairs)} 个问答对")
        return qa_pairs

    @staticmethod
    def _hash_question(text: str) -> str:
        """生成问题哈希"""
        normalized = " ".join(text.strip().lower().split())
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    @staticmethod
    def _calculate_quality(qa_pair: QAPair) -> float:
        """计算问答对质量评分"""
        score = qa_pair.confidence * 0.6  # 置信度占 60%

        # 回答长度适中（50-1000 字最佳）
        answer_len = len(qa_pair.answer)
        if 50 <= answer_len <= 1000:
            score += 0.2
        elif 20 <= answer_len <= 2000:
            score += 0.1

        # 问题长度适中（10-100 字最佳）
        question_len = len(qa_pair.question)
        if 10 <= question_len <= 100:
            score += 0.2
        elif 5 <= question_len <= 200:
            score += 0.1

        return min(score, 1.0)


# 全局 Q&A 提取器实例
qa_extractor = QAExtractor()