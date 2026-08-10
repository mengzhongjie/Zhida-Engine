"""Langfuse 完整链路观测；SDK/网络异常绝不影响问答。"""
from urllib.parse import urlparse

from loguru import logger
from app.core.config import LANGFUSE_CLOUD_HOST, settings


async def observe_qa(**data) -> None:
    if not settings.LANGFUSE_ENABLED or not settings.LANGFUSE_PUBLIC_KEY or not settings.LANGFUSE_SECRET_KEY:
        return
    try:
        parsed_host = urlparse(settings.LANGFUSE_HOST)
        trusted_host = (
            parsed_host.scheme == "https"
            and parsed_host.hostname == "cloud.langfuse.com"
            and parsed_host.port in {None, 443}
            and not parsed_host.username
            and not parsed_host.password
        )
    except ValueError:
        trusted_host = False
    if not trusted_host:
        logger.warning("Langfuse Host 不在固定可信域名内，已拒绝上报")
        return
    try:
        from langfuse import Langfuse
        client = Langfuse(public_key=settings.LANGFUSE_PUBLIC_KEY, secret_key=settings.LANGFUSE_SECRET_KEY, host=LANGFUSE_CLOUD_HOST)
        retrieval_chunks = data.get("retrieval_chunks", [])
        trace_input = {"question": data.get("question", "")}
        trace_output = None
        if settings.LANGFUSE_ONLINE_EVALUATION_ENABLED:
            # Langfuse v4 的在线 Evaluator 以 Trace 为目标，而非内部 Generation。
            # 因此将完整评分材料放到根 Trace，标准 Context/Faithfulness 等评估器才能触发。
            trace_input["retrieval_context"] = retrieval_chunks
            trace_output = {"answer": data.get("answer", "")}
        trace = client.start_observation(
            name="rag-answer",
            as_type="span",
            input=trace_input,
            output=trace_output,
            metadata={**data.get("metadata", {}), "user_id": data.get("user_id"), "session_id": data.get("session_id")},
        )
        # 这是 Langfuse 中评估“无关引用”的证据。不要只传文件名：同一长文档的
        # 不同父块也可能一个相关、另一个完全跑题。
        retrieval = trace.start_observation(
            name="retrieval",
            as_type="span",
            input={"question": data.get("question", "")},
            output={"chunks": retrieval_chunks},
            metadata={"result_count": len(retrieval_chunks)},
        )
        retrieval.end()
        generation_kwargs = {
            "name": "answer",
            "model": data.get("model", "unknown"),
            "output": data.get("answer", ""),
            "metadata": data.get("metadata", {}),
            "usage": {"input": data.get("input_tokens", 0), "output": data.get("output_tokens", 0)},
        }
        if settings.LANGFUSE_ONLINE_EVALUATION_ENABLED:
            # 让 Langfuse 平台的 LLM-as-a-Judge 在 answer 节点取得完整评分材料。
            generation_kwargs["input"] = {
                "question": data.get("question", ""),
                "retrieval_context": retrieval_chunks,
            }
        generation = trace.start_observation(as_type="generation", **generation_kwargs)
        generation.end()
        trace.end()
        client.flush()
        logger.info("Langfuse 观测已上报：model={}, source={}", data.get("model", "unknown"), data.get("metadata", {}).get("source", "sync"))
    except Exception as exc:
        logger.warning(f"Langfuse 观测写入失败（不影响问答）: {exc}")
