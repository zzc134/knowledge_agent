"""文档加载器：解析 → 分块 → embedding → 存入数据库"""

from sqlalchemy import text
from db.database import async_session
from db.models import Document, Chunk
from .parser import parse_document
from .chunker import chunk_text
from .embedder import embed_texts


async def load_document(
    title: str,
    content: str,
    source_type: str = "markdown",
    source_url: str | None = None,
) -> str:
    """
    加载一篇文档：解析 → 分块 → embedding → 存入数据库。
    返回 document_id。
    """
    # 1. 解析
    cleaned_text = parse_document(content, source_type)

    # 2. 分块
    chunks = chunk_text(cleaned_text)
    if not chunks:
        raise ValueError("文档分块后为空")

    # 3. 批量 embedding
    chunk_contents = [c['content'] for c in chunks]
    embeddings = embed_texts(chunk_contents)

    # 4. 存入数据库
    async with async_session() as session:
        doc = Document(
            title=title,
            source_url=source_url,
            source_type=source_type,
            raw_content=content,
        )
        session.add(doc)
        await session.flush()

        for i, (chunk_data, embedding) in enumerate(zip(chunks, embeddings)):
            chunk = Chunk(
                document_id=doc.id,
                content=chunk_data['content'],
                chunk_index=i,
                dense_embedding=embedding,
                metadata_={"title": title},
            )
            session.add(chunk)

        await session.commit()

    # 5. 异步更新 tsvector 全文检索列
    await _update_tsvector()

    return doc.id


async def _update_tsvector() -> None:
    """为所有未生成 tsvector 的 chunk 生成全文检索向量"""
    async with async_session() as session:
        await session.execute(
            text("UPDATE chunks SET tsv = to_tsvector('simple', content) WHERE tsv IS NULL")
        )
        await session.commit()
