"""对真实知识库运行可标注的 RAG 检索评测（只读）。

用法：
  python scripts/validate_rag_retrieval.py 5
  python scripts/validate_rag_retrieval.py 5 --cases tests/fixtures/rag_cases.jsonl --report /tmp/rag-report.json

JSONL 每行一个问题。建议先用无标注模式导出候选 parent_id，再由人工标注：
  {"question":"如何开发 RAG", "expected_parent_ids":["doc_9_parent_123"]}

也可在文档级别标注（适用于一个问题只对应少数独立文档的知识库）：
  {"question":"报销流程", "expected_document_ids":[12]}
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.v1.embedding.router import init_embedding_config  # noqa: E402
from app.core.database import async_session_factory, engine  # noqa: E402
from app.services.knowledge.indexer import index_manager  # noqa: E402
from app.services.qa.retriever import hybrid_retriever  # noqa: E402


QUERIES = (
    "量子计算",
    "如何开发RAG",
    "Agent工程师面试",
    "Raft 一致性哈希",
    "多Agent协作",
)


def _load_cases(path: str | None) -> list[dict]:
    if not path:
        return [{"question": query} for query in QUERIES]
    cases: list[dict] = []
    with Path(path).open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                case = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"第 {line_number} 行不是有效 JSON") from exc
            if not isinstance(case, dict) or not isinstance(case.get("question"), str):
                raise ValueError(f"第 {line_number} 行必须包含 question 字符串")
            cases.append(case)
    if not cases:
        raise ValueError("评测集不能为空")
    return cases


def _is_relevant(result, case: dict) -> bool | None:
    """没有人工标注时返回 None，避免把猜测误当评测真值。"""
    metadata = result.metadata or {}
    expected_parents = {str(value) for value in case.get("expected_parent_ids", [])}
    expected_documents = {str(value) for value in case.get("expected_document_ids", [])}
    if not expected_parents and not expected_documents:
        return None
    return (
        str(metadata.get("parent_id", "")) in expected_parents
        or str(metadata.get("document_id", "")) in expected_documents
    )


def _evaluate_case(case: dict, results: list) -> dict:
    judged = [_is_relevant(result, case) for result in results]
    has_labels = any(value is not None for value in judged)
    row = {
        "question": case["question"],
        "expected_parent_ids": case.get("expected_parent_ids", []),
        "expected_document_ids": case.get("expected_document_ids", []),
        "results": [
            {
                "rank": rank,
                "score": result.score,
                "filename": (result.metadata or {}).get("filename", "未知来源"),
                "document_id": (result.metadata or {}).get("document_id"),
                "parent_id": (result.metadata or {}).get("parent_id"),
                "relevant": judged[rank - 1],
                "snippet": " ".join(result.text.split())[:180],
            }
            for rank, result in enumerate(results, start=1)
        ],
    }
    if has_labels:
        relevant_ranks = [index + 1 for index, value in enumerate(judged) if value]
        row["precision_at_k"] = round(len(relevant_ranks) / max(len(results), 1), 4)
        row["recall_at_k"] = 1.0 if relevant_ranks else 0.0
        row["mrr"] = round(1 / relevant_ranks[0], 4) if relevant_ranks else 0.0
        row["irrelevant_retrieved"] = len(results) - len(relevant_ranks)
    return row


def _summary(rows: list[dict]) -> dict:
    labelled = [row for row in rows if "precision_at_k" in row]
    if not labelled:
        return {"labelled_cases": 0, "message": "尚未标注期望父块/文档；结果仅供人工判定。"}
    return {
        "labelled_cases": len(labelled),
        "precision_at_k": round(sum(row["precision_at_k"] for row in labelled) / len(labelled), 4),
        "recall_at_k": round(sum(row["recall_at_k"] for row in labelled) / len(labelled), 4),
        "mrr": round(sum(row["mrr"] for row in labelled) / len(labelled), 4),
        "irrelevant_retrieved": sum(row["irrelevant_retrieved"] for row in labelled),
    }


async def validate(kb_id: int, cases: list[dict], top_k: int) -> dict:
    async with async_session_factory() as db:
        await init_embedding_config(db)

    collection = index_manager._get_collection(str(kb_id))
    print(f"集合={collection.name}, 数量={collection.count()}, 参数={collection.metadata}")
    rows = []
    for case in cases:
        results = await hybrid_retriever.retrieve([str(kb_id)], case["question"], top_k=top_k)
        row = _evaluate_case(case, results)
        rows.append(row)
        print(f"\n{case['question']}")
        for result in row["results"]:
            relevance = "相关" if result["relevant"] is True else "无关" if result["relevant"] is False else "待标注"
            print(f"  {result['rank']}. [{relevance}] {result['filename']} score={result['score']:.4f} parent={result['parent_id']} | {result['snippet'][:100]}")
    summary = _summary(rows)
    print(f"\n评测汇总：{json.dumps(summary, ensure_ascii=False)}")
    return {"knowledge_base_id": kb_id, "top_k": top_k, "summary": summary, "cases": rows}


async def run(kb_id: int, cases: list[dict], top_k: int) -> dict:
    try:
        return await validate(kb_id, cases, top_k)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="验证真实 RAG 检索")
    parser.add_argument("knowledge_base_id", type=int)
    parser.add_argument("--cases", help="JSONL 评测集；每行包含 question 和人工标注的 expected_parent_ids/document_ids")
    parser.add_argument("--top-k", type=int, default=3, choices=range(1, 11))
    parser.add_argument("--report", help="将结构化评测结果写入 JSON 文件")
    args = parser.parse_args()
    report = asyncio.run(run(args.knowledge_base_id, _load_cases(args.cases), args.top_k))
    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"评测报告已写入：{args.report}")


if __name__ == "__main__":
    main()
