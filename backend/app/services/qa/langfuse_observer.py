"""可选 Langfuse Cloud 观测；SDK/网络异常绝不影响问答。"""
from loguru import logger
from app.core.config import settings


async def observe_qa(**data) -> None:
    if not settings.LANGFUSE_ENABLED or not settings.LANGFUSE_PUBLIC_KEY or not settings.LANGFUSE_SECRET_KEY:
        return
    try:
        from langfuse import Langfuse
        client = Langfuse(public_key=settings.LANGFUSE_PUBLIC_KEY, secret_key=settings.LANGFUSE_SECRET_KEY, host=settings.LANGFUSE_HOST)
        trace = client.trace(name="rag-answer", user_id=data.get("user_id"), session_id=data.get("session_id"), input={"question": data.get("question", "")})
        trace.generation(name="answer", model=data.get("model", "unknown"), output=data.get("answer", ""), metadata=data.get("metadata", {}), usage={"input": data.get("input_tokens", 0), "output": data.get("output_tokens", 0)})
        client.flush()
        logger.info("Langfuse 观测已上报：model={}, source={}", data.get("model", "unknown"), data.get("metadata", {}).get("source", "sync"))
    except Exception as exc:
        logger.warning(f"Langfuse 观测写入失败（不影响问答）: {exc}")
