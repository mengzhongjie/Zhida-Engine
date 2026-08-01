"""可选 Langfuse Cloud 观测；SDK/网络异常绝不影响问答。"""
import json

from loguru import logger
from app.core.config import settings


async def _evaluate_rag_trace(client, trace_id: str, question: str, answer: str, retrieval_chunks: list[dict]) -> None:
    """使用专属评测模型评分；只传本轮 RAG 证据，绝不继承会话上下文。"""
    if not settings.LANGFUSE_EVALUATOR_ENABLED or not settings.LANGFUSE_EVALUATOR_MODEL_CONFIG_ID:
        return
    try:
        from openai import AsyncOpenAI
        from app.core.database import async_session_factory
        from app.core.security import decrypt_api_key
        from app.models.llm_config import LLMConfig

        async with async_session_factory() as db:
            model_config = await db.get(LLMConfig, settings.LANGFUSE_EVALUATOR_MODEL_CONFIG_ID)
        if model_config is None or not model_config.is_active:
            raise RuntimeError("独立评测模型不存在或未启用")
        if "deepseek" in f"{model_config.provider_id} {model_config.model_name}".lower():
            raise RuntimeError("独立评测模型不能使用 DeepSeek")

        payload = {
            "question": question,
            "retrieved_chunks": retrieval_chunks,
            "answer": answer,
        }
        prompt = (
            "你是严格的 RAG 评测员。只根据给出的问题、检索片段和回答评分，不使用外部知识。"
            "返回纯 JSON，包含三个 0 到 1 的数字字段：context_precision（检索片段相关性）、"
            "citation_correctness（片段能否支持回答）、answer_groundedness（回答是否有证据支撑），"
            "以及 reason（不超过 120 字）。\n\n"
            + json.dumps(payload, ensure_ascii=False)
        )
        api_key = decrypt_api_key(model_config.api_key) or "not-needed"
        llm = AsyncOpenAI(base_url=model_config.base_url, api_key=api_key, timeout=45.0)
        response = await llm.chat.completions.create(
            model=model_config.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=300,
        )
        content = (response.choices[0].message.content or "").strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        scores = json.loads(content)
        reason = str(scores.get("reason", ""))[:300]
        for name in ("context_precision", "citation_correctness", "answer_groundedness"):
            value = float(scores[name])
            if not 0 <= value <= 1:
                raise ValueError(f"{name} 必须在 0 到 1 之间")
            client.score(name=name, value=value, data_type="NUMERIC", trace_id=trace_id, comment=reason)
        client.flush()
        logger.info("Langfuse RAG 评测已完成：trace={}, model={}", trace_id, model_config.model_name)
    except Exception as exc:
        logger.warning(f"Langfuse RAG 评测失败（不影响问答和 Trace）: {exc}")


async def observe_qa(**data) -> None:
    if not settings.LANGFUSE_ENABLED or not settings.LANGFUSE_PUBLIC_KEY or not settings.LANGFUSE_SECRET_KEY:
        return
    try:
        from langfuse import Langfuse
        client = Langfuse(public_key=settings.LANGFUSE_PUBLIC_KEY, secret_key=settings.LANGFUSE_SECRET_KEY, host=settings.LANGFUSE_HOST)
        retrieval_chunks = data.get("retrieval_chunks", [])
        trace = client.trace(
            name="rag-answer",
            user_id=data.get("user_id"),
            session_id=data.get("session_id"),
            input={"question": data.get("question", "")},
            metadata=data.get("metadata", {}),
        )
        # 这是 Langfuse 中评估“无关引用”的证据。不要只传文件名：同一长文档的
        # 不同父块也可能一个相关、另一个完全跑题。
        trace.span(
            name="retrieval",
            input={"question": data.get("question", "")},
            output={"chunks": retrieval_chunks},
            metadata={"result_count": len(retrieval_chunks)},
        )
        trace.generation(
            name="answer",
            model=data.get("model", "unknown"),
            output=data.get("answer", ""),
            metadata=data.get("metadata", {}),
            usage={"input": data.get("input_tokens", 0), "output": data.get("output_tokens", 0)},
        )
        client.flush()
        await _evaluate_rag_trace(
            client, trace.id, data.get("question", ""), data.get("answer", ""), retrieval_chunks,
        )
        logger.info("Langfuse 观测已上报：model={}, source={}", data.get("model", "unknown"), data.get("metadata", {}).get("source", "sync"))
    except Exception as exc:
        logger.warning(f"Langfuse 观测写入失败（不影响问答）: {exc}")
