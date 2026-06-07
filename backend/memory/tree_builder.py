"""Memory Tree 构建器。

当前先实现 Source Tree 的最小闭环：
- L0: 现有 chunks 表里的原始分块
- L1: 每篇 Document 的摘要节点
- L2: 每种 source_type 的来源概览节点

后续 Topic Tree / Global Tree 可以复用这里的 upsert 和建边逻辑。
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy import delete, select

from db.database import async_session
from db.models import Chunk, Document, MemoryEdge, MemoryNode


@dataclass
class BuildStats:
    """构建结果统计，方便命令行和评估脚本输出。"""

    documents: int = 0
    source_roots: int = 0
    edges: int = 0
    skipped_empty_documents: int = 0



#存id
def source_document_key(document: Document) -> str:
    """生成 Source Tree 中单篇文档 L1 节点的稳定 key。"""
    return f"source:{document.source_type}:document:{document.id}"


def source_root_key(source_type: str) -> str:
    """生成 Source Tree 中来源 L2 节点的稳定 key。"""
    return f"source:{source_type}"


#后面重构，现在只是截断是吗
def _compact_text(text: str, max_chars: int) -> str:
    """把 chunk 文本压成适合放入摘要提示或兜底摘要的短片段。"""
    compacted = " ".join(text.split())
    if len(compacted) <= max_chars:
        return compacted
    return compacted[: max_chars - 1] + "..."



#生成摘要
def summarize_document_chunks(
    title: str,
    source_type: str,
    chunks: list[Chunk],
    max_chunks: int = 6,
) -> str:
    """为一篇文档生成 L1 摘要。

    第一版使用抽取式兜底摘要，不依赖 LLM。
    这样 Tree Builder 可以在本地稳定跑通；后续可以替换成 LLM 摘要。
    """
    snippets = [
        f"- chunk {chunk.chunk_index}: {_compact_text(chunk.content, 220)}"
        for chunk in chunks[:max_chunks]
    ]
    more = ""
    if len(chunks) > max_chunks:
        more = f"\n- 另有 {len(chunks) - max_chunks} 个 chunk 未展开。"

    return (
        f"文档《{title}》来自 {source_type}，共包含 {len(chunks)} 个原始 chunk。\n"
        "主要内容片段：\n"
        + "\n".join(snippets)
        + more
    )


#同样，为L1生成摘要
def summarize_source_nodes(
    source_type: str,
    document_nodes: list[MemoryNode],
    max_nodes: int = 8,
) -> str:
    """为一个来源生成 L2 概览摘要。"""
    snippets = [
        f"- {node.title}: {_compact_text(node.summary, 180)}"
        for node in document_nodes[:max_nodes]
    ]
    more = ""
    if len(document_nodes) > max_nodes:
        more = f"\n- 另有 {len(document_nodes) - max_nodes} 个文档摘要未展开。"

    return (
        f"来源 {source_type} 下共有 {len(document_nodes)} 个文档摘要节点。\n"
        "文档概览：\n"
        + "\n".join(snippets)
        + more
    )


async def _embed_summary(summary: str, with_embedding: bool) -> list[float] | None:
    """按需生成摘要向量。

    默认不生成 embedding，避免构建树时强制加载 bge-m3。
    需要 Tree Retriever 做向量检索时，再用 --with-embedding 打开。
    """
    if not with_embedding:
        return None

    from ingestion.embedder import embed_text

    return embed_text(summary)


#因为在后面使用的时候这个upsert_memory_node需要大量使用，通过tree_type + key 构建ID
async def _upsert_memory_node(
    session,
    *,
    tree_type: str,
    level: int,
    key: str,
    title: str,
    summary: str,
    dense_embedding: list[float] | None,
    time_start: datetime | None = None,
    time_end: datetime | None = None,
    metadata_: dict | None = None,
) -> MemoryNode:
    """按 tree_type + key 更新或创建节点。

    目前数据库还没有唯一约束，所以这里在应用层做 upsert。
    """
    result = await session.execute(
        select(MemoryNode).where(
            MemoryNode.tree_type == tree_type,
            MemoryNode.key == key,
        )
    )
    node = result.scalar_one_or_none()

    if node is None:
        node = MemoryNode(
            tree_type=tree_type,
            level=level,
            key=key,
            title=title,
            summary=summary,
            dense_embedding=dense_embedding,
            time_start=time_start,
            time_end=time_end,
            metadata_=metadata_,
        )
        session.add(node)
        await session.flush()
        return node

    node.level = level
    node.title = title
    node.summary = summary
    # 不带 --with-embedding 重建树时，不清空之前已经生成过的摘要向量。
    if dense_embedding is not None:
        node.dense_embedding = dense_embedding
    node.time_start = time_start
    node.time_end = time_end
    node.metadata_ = metadata_
    return node


async def build_source_tree(
    document_id: str | None = None,
    *,
    with_embedding: bool = False,
) -> BuildStats:
    """从现有 documents/chunks 构建 Source Tree。

    如果传入 document_id，只重建这篇文档的 L1 节点；
    对应 source_type 的 L2 来源节点会基于该来源下全部 L1 节点重新汇总。
    """
    stats = BuildStats()
    touched_source_types: set[str] = set()

    #构建数据库
    async with async_session() as session:
        document_stmt = select(Document).order_by(Document.created_at)
        if document_id:
            document_stmt = document_stmt.where(Document.id == document_id)

        document_result = await session.execute(document_stmt)
        documents = document_result.scalars().all()

        for document in documents:
            chunk_result = await session.execute(
                select(Chunk)
                .where(Chunk.document_id == document.id)
                .order_by(Chunk.chunk_index)
            )
            chunks = chunk_result.scalars().all()
            if not chunks:
                stats.skipped_empty_documents += 1
                continue

            summary = summarize_document_chunks(
                document.title,
                document.source_type,
                chunks,
            )
            node = await _upsert_memory_node(
                session,
                tree_type="source",
                level=1,
                key=source_document_key(document),
                title=f"文档摘要：{document.title}",
                summary=summary,
                dense_embedding=await _embed_summary(summary, with_embedding),
                time_start=document.created_at,
                time_end=document.created_at,
                metadata_={
                    "document_id": document.id,
                    "source_type": document.source_type,
                    "source_url": document.source_url,
                    "chunk_count": len(chunks),
                },
            )

            # 重建当前文档摘要节点到 L0 chunks 的边，避免重复运行产生重复边。
            await session.execute(
                delete(MemoryEdge).where(MemoryEdge.parent_node_id == node.id)
            )
            for chunk in chunks:
                session.add(
                    MemoryEdge(
                        parent_node_id=node.id,
                        chunk_id=chunk.id,
                        relation_type="contains",
                        weight=1.0,
                    )
                )
                stats.edges += 1

            stats.documents += 1
            touched_source_types.add(document.source_type)

        for source_type in sorted(touched_source_types):
            # L2 来源节点要覆盖该来源下全部 L1 文档摘要，而不只是本次重建的文档。
            node_result = await session.execute(
                select(MemoryNode)
                .where(
                    MemoryNode.tree_type == "source",
                    MemoryNode.level == 1,
                    MemoryNode.key.like(f"{source_root_key(source_type)}:document:%"),
                )
                .order_by(MemoryNode.created_at)
            )
            document_nodes = node_result.scalars().all()
            if not document_nodes:
                continue

            summary = summarize_source_nodes(source_type, document_nodes)
            root_node = await _upsert_memory_node(
                session,
                tree_type="source",
                level=2,
                key=source_root_key(source_type),
                title=f"来源概览：{source_type}",
                summary=summary,
                dense_embedding=await _embed_summary(summary, with_embedding),
                metadata_={
                    "source_type": source_type,
                    "document_node_count": len(document_nodes),
                },
            )

            await session.execute(
                delete(MemoryEdge).where(MemoryEdge.parent_node_id == root_node.id)
            )
            for document_node in document_nodes:
                session.add(
                    MemoryEdge(
                        parent_node_id=root_node.id,
                        child_node_id=document_node.id,
                        relation_type="summarizes",
                        weight=1.0,
                    )
                )
                stats.edges += 1

            stats.source_roots += 1

        await session.commit()

    return stats


async def main() -> None:
    parser = argparse.ArgumentParser(description="构建 Memory Tree 的 Source Tree")
    parser.add_argument("--document-id", help="只重建指定 document_id 的 Source Tree")
    parser.add_argument(
        "--with-embedding",
        action="store_true",
        help="为摘要节点生成 embedding；首次运行可能加载 bge-m3 模型",
    )
    args = parser.parse_args()

    stats = await build_source_tree(
        document_id=args.document_id,
        with_embedding=args.with_embedding,
    )
    print(json.dumps(asdict(stats), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
