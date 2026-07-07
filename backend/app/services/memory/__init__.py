"""
智答引擎（ZhiDa Engine）—— 记忆层服务

基于 Mem0 的长期记忆层，从对话中自动提取用户偏好、事实、关系，
支持语义检索记忆，实现个性化、持续的对话体验。
"""

from app.services.memory.memory_service import memory_service

__all__ = ["memory_service"]
