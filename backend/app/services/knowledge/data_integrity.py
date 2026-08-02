"""SQLite/Chroma 轻量一致性检查与可恢复清理。"""

import asyncio
from datetime import datetime
from pathlib import Path
import sqlite3

from sqlalchemy import func, select, text

from app.core.config import settings
from app.core.database import async_session_factory
from app.models.knowledge import Document, KnowledgeBase
from app.services.knowledge.indexer import index_manager


class DataIntegrityService:
    async def report(self) -> dict:
        sqlite_status = "ok"
        sqlite_detail = "ok"
        try:
            async with async_session_factory() as db:
                quick_check = (await db.execute(text("PRAGMA quick_check"))).scalar()
                if quick_check != "ok":
                    raise RuntimeError(f"SQLite quick_check: {quick_check}")
                row = (await db.execute(select(Document))).scalars().all()
            completed = [d for d in row if d.status == "completed"]
            cleanup = [d for d in row if d.status == "cleanup_pending"]
            inconsistent = []
            for document in completed:
                actual = index_manager.get_document_chunk_count(document.knowledge_base_id, document.id)
                if actual != document.chunk_count:
                    inconsistent.append({"document_id": document.id, "filename": document.filename,
                                         "sqlite_chunks": document.chunk_count, "chroma_chunks": actual})
        except Exception as exc:
            sqlite_status, sqlite_detail, inconsistent, cleanup = "error", str(exc)[:300], [], []
        backups = sorted((settings.DATA_DIR / "backups").glob("zhida_engine-*.db"), reverse=True)
        return {"sqlite_status": sqlite_status, "sqlite_detail": sqlite_detail,
                "cleanup_pending": len(cleanup), "inconsistent_documents": inconsistent,
                "latest_backup": backups[0].name if backups else None}

    async def cleanup_pending(self) -> int:
        async with async_session_factory() as db:
            docs = (await db.execute(select(Document).where(Document.status == "cleanup_pending"))).scalars().all()
            ids = [doc.id for doc in docs]
        # 不复用 API 的 Session；这里直接执行与删除流程相同的跨存储顺序。
        removed = 0
        for doc_id in ids:
            async with async_session_factory() as db:
                doc = await db.get(Document, doc_id)
                if not doc:
                    continue
                try:
                    await index_manager.remove_document_chunks(doc.knowledge_base_id, doc.id)
                    await db.delete(doc)
                    kb = await db.get(KnowledgeBase, doc.knowledge_base_id)
                    if kb:
                        counts = (await db.execute(select(
                            func.count(Document.id), func.coalesce(func.sum(Document.chunk_count), 0),
                            func.coalesce(func.sum(Document.parent_chunk_count), 0), func.coalesce(func.sum(Document.file_size), 0),
                        ).where(Document.knowledge_base_id == kb.id))).one()
                        kb.document_count, kb.chunk_count, kb.parent_chunk_count, kb.total_size_bytes = counts
                    await db.commit()
                    removed += 1
                except Exception:
                    await db.rollback()
        return removed

    async def backup(self) -> str:
        source = Path(settings.db_url.removeprefix("sqlite+aiosqlite:///"))
        folder = settings.DATA_DIR / "backups"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"zhida_engine-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.db"
        def create_backup():
            source_db = sqlite3.connect(source)
            target_db = sqlite3.connect(target)
            try:
                source_db.backup(target_db)
            finally:
                target_db.close(); source_db.close()
        await asyncio.to_thread(create_backup)
        for old in sorted(folder.glob("zhida_engine-*.db"), reverse=True)[5:]:
            old.unlink(missing_ok=True)
        return target.name


data_integrity_service = DataIntegrityService()
