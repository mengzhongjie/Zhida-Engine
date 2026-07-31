"""对真实知识库运行轻量 RAG 黄金查询，只读验证检索结果。"""

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


async def validate(kb_id: int) -> None:
    async with async_session_factory() as db:
        await init_embedding_config(db)

    collection = index_manager._get_collection(str(kb_id))
    print(f"集合={collection.name}, 数量={collection.count()}, 参数={collection.metadata}")
    for query in QUERIES:
        results = await hybrid_retriever.retrieve([str(kb_id)], query, top_k=3)
        print(f"\n{query}")
        for rank, result in enumerate(results, start=1):
            metadata = result.metadata or {}
            snippet = " ".join(result.text.split())[:100]
            print(
                f"  {rank}. {metadata.get('filename', '未知来源')} "
                f"score={result.score:.4f} parent={metadata.get('parent_id')} | {snippet}"
            )


async def run(kb_id: int) -> None:
    try:
        await validate(kb_id)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="验证真实 RAG 检索")
    parser.add_argument("knowledge_base_id", type=int)
    args = parser.parse_args()
    asyncio.run(run(args.knowledge_base_id))


if __name__ == "__main__":
    main()
