"""文档加载器：解析 → 分块 → embedding → 存入数据库"""

import asyncio

from sqlalchemy import text
from db.database import async_session
from db.models import Document, Chunk
from .parser import parse_document
from .chunker import chunk_text
from .embedder import embed_texts
from .topics import normalize_topics
from .topic_extractor import extract_topics_for_chunks


async def load_document(
    title: str,
    content: str,
    source_type: str = "markdown",
    source_url: str | None = None,
    topics: list[str] | None = None,
    auto_topics: bool = True,
    update_memory_tree: bool = True,
    memory_tree_background: bool = True,
) -> str:
    """
    加载一篇文档：解析 → 分块 → embedding → 存入数据库。
    topics 会写入每个 chunk 的 metadata_["topics"]，作为 Topic Tree 的入库主题标签。
    auto_topics=True 时，会为每个 chunk 并发调用 LLM 生成 chunk 级 topics。
    update_memory_tree=True 时，入库后自动更新 Source Tree 和 Topic Tree。
    memory_tree_background=True 时，Memory Tree 更新会在后台执行，入库可更快返回。
    返回 document_id。
    """
    normalized_topics = normalize_topics(topics)

    # 1. 解析
    cleaned_text = parse_document(content, source_type)

    # 2. 分块
    chunks = chunk_text(cleaned_text)
    if not chunks:
        raise ValueError("文档分块后为空")

    # 3. 并发抽取每个 chunk 的 topic；失败时 topic_extractor 会回退到手动 topics。
    if auto_topics:
        chunk_topics = await extract_topics_for_chunks(
            title=title,
            chunks=chunks,
            seed_topics=normalized_topics,
        )
    else:
        chunk_topics = [normalized_topics for _ in chunks]

    # 4. 批量 embedding
    chunk_contents = [c['content'] for c in chunks]
    embeddings = embed_texts(chunk_contents)

    # 5. 存入数据库
    async with async_session() as session:
        doc = Document(
            title=title,
            source_url=source_url,
            source_type=source_type,
            raw_content=content,
        )
        session.add(doc)
        await session.flush()

        for i, (chunk_data, embedding, topics_for_chunk) in enumerate(
            zip(chunks, embeddings, chunk_topics)
        ):
            chunk = Chunk(
                document_id=doc.id,
                content=chunk_data['content'],
                chunk_index=i,
                dense_embedding=embedding,
                metadata_={
                    "title": title,
                    "source_type": source_type,
                    "source_url": source_url,
                    "topics": topics_for_chunk,
                },
            )
            session.add(chunk)

        await session.commit()

    # 6. 异步更新 tsvector 全文检索列
    await _update_tsvector()

    # 7. 自动更新 Memory Tree，让新文档立即进入层级记忆。
    if update_memory_tree:
        if memory_tree_background:
            schedule_memory_tree_update(doc.id)
        else:
            await _update_memory_tree_for_document(doc.id)

    return doc.id


async def _update_tsvector() -> None:
    """为所有未生成 tsvector 的 chunk 生成全文检索向量"""
    async with async_session() as session:
        await session.execute(
            text("UPDATE chunks SET tsv = to_tsvector('simple', content) WHERE tsv IS NULL")
        )
        await session.commit()


async def _update_memory_tree_for_document(document_id: str) -> None:
    """文档入库后更新 Memory Tree。

    Source Tree 只重建当前文档对应的 L1 节点和来源 L2 节点；
    Topic Tree 第一版仍做全量重建，因为一个新 chunk 可能属于多个 topic。
    """
    from memory.tree_builder import build_source_tree, build_topic_tree

    await build_source_tree(document_id=document_id)
    await build_topic_tree()


async def _run_memory_tree_update_task(document_id: str) -> None:
    """后台更新 Memory Tree，并吞掉异常，避免 task exception 未被消费。"""
    try:
        await _update_memory_tree_for_document(document_id)
    except Exception:
        # 第一版不引入任务表；后续可把异常写入 memory_jobs。
        pass


def schedule_memory_tree_update(document_id: str) -> asyncio.Task:
    """调度 Memory Tree 后台更新任务。"""
    return asyncio.create_task(_run_memory_tree_update_task(document_id))
