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
import re
from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy import delete, or_, select

from db.database import async_session
from db.models import Chunk, Document, MemoryEdge, MemoryNode, UserInterest
from memory.summarizer import summarize_chunks_with_llm, summarize_nodes_with_llm


@dataclass
class BuildStats:
    """构建结果统计，方便命令行和评估脚本输出。"""

    documents: int = 0
    source_roots: int = 0
    topics: int = 0
    topic_groups: int = 0
    edges: int = 0
    skipped_empty_documents: int = 0
    skipped_empty_topics: int = 0



#存id
def source_document_key(document: Document) -> str:
    """生成 Source Tree 中单篇文档 L1 节点的稳定 key。"""
    return f"source:{document.source_type}:document:{document.id}"


def source_root_key(source_type: str) -> str:
    """生成 Source Tree 中来源 L2 节点的稳定 key。"""
    return f"source:{source_type}"



#将topic规范化
def normalize_topic(topic: str) -> str:
    """把用户兴趣 topic 规范成适合做 key 的形式。"""
    normalized = topic.strip().lower()
    normalized = re.sub(r"\s+", "-", normalized)
    normalized = re.sub(r"[^a-z0-9_\-:\u4e00-\u9fff]+", "", normalized)
    return normalized or "unknown"


def topic_root_key(topic: str) -> str:
    """生成 Topic Tree 中单个主题 L2 节点的稳定 key。"""
    return f"topic:{normalize_topic(topic)}"


def topic_group_key(topic: str, group_index: int) -> str:
    """生成 Topic Tree 中主题分组 L1 节点的稳定 key。"""
    return f"{topic_root_key(topic)}:group:{group_index}"


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


def summarize_topic_chunks(
    topic: str,
    chunks: list[Chunk],
    group_index: int,
    max_chunks: int = 6,
) -> str:
    """为某个主题下的一组 chunks 生成 L1 摘要。"""
    snippets = [
        f"- chunk {chunk.chunk_index}: {_compact_text(chunk.content, 220)}"
        for chunk in chunks[:max_chunks]
    ]
    more = ""
    if len(chunks) > max_chunks:
        more = f"\n- 另有 {len(chunks) - max_chunks} 个 chunk 未展开。"

    return (
        f"主题《{topic}》的第 {group_index + 1} 组内容，共包含 {len(chunks)} 个原始 chunk。\n"
        "相关内容片段：\n"
        + "\n".join(snippets)
        + more
    )


def summarize_topic_nodes(
    topic: str,
    group_nodes: list[MemoryNode],
    max_nodes: int = 8,
) -> str:
    """为一个主题生成 L2 概览摘要。"""
    snippets = [
        f"- {node.title}: {_compact_text(node.summary, 180)}"
        for node in group_nodes[:max_nodes]
    ]
    more = ""
    if len(group_nodes) > max_nodes:
        more = f"\n- 另有 {len(group_nodes) - max_nodes} 个主题分组摘要未展开。"

    return (
        f"主题 {topic} 下共有 {len(group_nodes)} 个分组摘要节点。\n"
        "主题概览：\n"
        + "\n".join(snippets)
        + more
    )


def topic_match_tokens(topic: str) -> list[str]:
    """从 topic 中提取用于匹配 chunk 的关键词。"""
    normalized = topic.strip().lower()
    tokens = re.findall(r"[a-zA-Z0-9_:-]+|[\u4e00-\u9fff]{2,}", normalized)
    if normalized and normalized not in tokens:
        tokens.insert(0, normalized)

    seen = set()
    result = []
    for token in tokens:
        token = token.strip()
        if len(token) >= 2 and token not in seen:
            seen.add(token)
            result.append(token)
    return result


def chunk_groups(chunks: list[Chunk], group_size: int) -> list[list[Chunk]]:
    """把命中的 chunks 切成 L1 分组。"""
    return [chunks[i : i + group_size] for i in range(0, len(chunks), group_size)]


def chunk_topics(chunk: Chunk) -> list[str]:
    """读取 chunk metadata 中的入库主题标签。"""
    metadata = chunk.metadata_ or {}
    raw_topics = metadata.get("topics") or []
    if isinstance(raw_topics, str):
        raw_topics = [raw_topics]

    topics = []
    seen = set()
    for topic in raw_topics:
        topic_text = str(topic).strip().lower()
        if topic_text and topic_text not in seen:
            seen.add(topic_text)
            topics.append(topic_text)
    return topics


async def _embed_summary(summary: str, with_embedding: bool) -> list[float] | None:
    """按需生成摘要向量。

    默认不生成 embedding，避免构建树时强制加载 bge-m3。
    需要 Tree Retriever 做向量检索时，再用 --with-embedding 打开。
    """
    if not with_embedding:
        return None

    from ingestion.embedder import embed_text

    return embed_text(summary)


async def _summarize_chunks(
    *,
    fallback_summary: str,
    title: str,
    topic_hint: str,
    chunks: list[Chunk],
    with_llm_summary: bool,
) -> str:
    """优先使用 LLM 生成 L1 摘要，失败时返回抽取式兜底摘要。"""
    if not with_llm_summary:
        return fallback_summary

    try:
        summary = await summarize_chunks_with_llm(
            title=title,
            topic_hint=topic_hint,
            chunk_texts=[chunk.content for chunk in chunks],
        )
    except Exception:
        return fallback_summary

    return summary or fallback_summary


async def _summarize_nodes(
    *,
    fallback_summary: str,
    title: str,
    topic_hint: str,
    child_nodes: list[MemoryNode],
    with_llm_summary: bool,
) -> str:
    """优先使用 LLM 生成 L2 摘要，失败时返回抽取式兜底摘要。"""
    if not with_llm_summary:
        return fallback_summary

    try:
        summary = await summarize_nodes_with_llm(
            title=title,
            topic_hint=topic_hint,
            child_summaries=[node.summary for node in child_nodes],
        )
    except Exception:
        return fallback_summary

    return summary or fallback_summary


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


async def _find_chunks_for_topic(
    session,
    topic: str,
    *,
    max_chunks: int,
) -> list[Chunk]:
    """用用户兴趣 topic 在 chunks 和文档标题中找相关 L0 原始记忆。"""
    tokens = topic_match_tokens(topic)
    if not tokens:
        return []

    conditions = []
    for token in tokens[:8]:
        pattern = f"%{token}%"
        conditions.append(Chunk.content.ilike(pattern))
        conditions.append(Document.title.ilike(pattern))

    result = await session.execute(
        select(Chunk)
        .join(Document, Document.id == Chunk.document_id)
        .where(or_(*conditions))
        .order_by(Chunk.created_at, Chunk.chunk_index)
        .limit(max_chunks)
    )
    return result.scalars().all()


async def _delete_topic_nodes(session, topic: str) -> None:
    """重建某个 topic 前，清理旧 Topic Tree 节点和边。"""
    key_prefix = topic_root_key(topic)
    result = await session.execute(
        select(MemoryNode).where(
            MemoryNode.tree_type == "topic",
            or_(
                MemoryNode.key == key_prefix,
                MemoryNode.key.like(f"{key_prefix}:group:%"),
            ),
        )
    )
    old_nodes = result.scalars().all()
    old_ids = [node.id for node in old_nodes]
    if not old_ids:
        return

    await session.execute(
        delete(MemoryEdge).where(
            or_(
                MemoryEdge.parent_node_id.in_(old_ids),
                MemoryEdge.child_node_id.in_(old_ids),
            )
        )
    )
    await session.execute(delete(MemoryNode).where(MemoryNode.id.in_(old_ids)))


async def _collect_explicit_topic_chunks(
    session,
    *,
    max_chunks_per_topic: int,
) -> dict[str, list[Chunk]]:
    """从 Chunk.metadata_["topics"] 收集显式入库主题。

    这是 Topic Tree 的首选数据来源，比用 user_interests 关键词反查 chunks 更可靠。
    """
    result = await session.execute(select(Chunk).order_by(Chunk.created_at, Chunk.chunk_index))
    chunks = result.scalars().all()

    topic_chunks: dict[str, list[Chunk]] = {}
    for chunk in chunks:
        for topic in chunk_topics(chunk):
            bucket = topic_chunks.setdefault(topic, [])
            if len(bucket) < max_chunks_per_topic:
                bucket.append(chunk)

    return topic_chunks


async def _collect_interest_topic_chunks(
    session,
    *,
    min_confidence: float,
    max_chunks_per_topic: int,
    excluded_topics: set[str],
) -> dict[str, list[Chunk]]:
    """用 user_interests 兜底补充没有显式 metadata topic 的主题。"""
    interest_result = await session.execute(
        select(UserInterest)
        .where(
            UserInterest.is_dormant == False,
            UserInterest.confidence >= min_confidence,
        )
        .order_by(UserInterest.confidence.desc(), UserInterest.access_count.desc())
    )
    interests = interest_result.scalars().all()

    topic_chunks: dict[str, list[Chunk]] = {}
    for interest in interests:
        topic = interest.topic.strip().lower()
        if not topic or topic in excluded_topics:
            continue

        chunks = await _find_chunks_for_topic(
            session,
            topic,
            max_chunks=max_chunks_per_topic,
        )
        if chunks:
            topic_chunks[topic] = chunks

    return topic_chunks


async def build_source_tree(
    document_id: str | None = None,
    *,
    with_embedding: bool = False,
    with_llm_summary: bool = True,
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

            fallback_summary = summarize_document_chunks(
                document.title,
                document.source_type,
                chunks,
            )
            summary = await _summarize_chunks(
                fallback_summary=fallback_summary,
                title=document.title,
                topic_hint=f"source:{document.source_type}",
                chunks=chunks,
                with_llm_summary=with_llm_summary,
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

            fallback_summary = summarize_source_nodes(source_type, document_nodes)
            summary = await _summarize_nodes(
                fallback_summary=fallback_summary,
                title=f"来源概览：{source_type}",
                topic_hint=f"source:{source_type}",
                child_nodes=document_nodes,
                with_llm_summary=with_llm_summary,
            )
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


async def build_topic_tree(
    *,
    with_embedding: bool = False,
    with_llm_summary: bool = True,
    min_confidence: float = 0.3,
    max_chunks_per_topic: int = 30,
    chunk_group_size: int = 6,
) -> BuildStats:
    """构建 Topic Tree。

    L2: topic:{topic}
      -> L1: topic:{topic}:group:{n}
          -> L0: chunks

    优先使用 Chunk.metadata_["topics"] 里的入库主题标签；
    user_interests 只作为兜底来源，避免旧数据没有 topics 时完全建不出树。
    """
    stats = BuildStats()

    async with async_session() as session:
        explicit_topic_chunks = await _collect_explicit_topic_chunks(
            session,
            max_chunks_per_topic=max_chunks_per_topic,
        )
        interest_topic_chunks = await _collect_interest_topic_chunks(
            session,
            min_confidence=min_confidence,
            max_chunks_per_topic=max_chunks_per_topic,
            excluded_topics=set(explicit_topic_chunks),
        )
        topics_to_chunks = {**explicit_topic_chunks, **interest_topic_chunks}

        for topic, chunks in sorted(topics_to_chunks.items()):
            if not topic:
                stats.skipped_empty_topics += 1
                continue

            if not chunks:
                stats.skipped_empty_topics += 1
                continue

            await _delete_topic_nodes(session, topic)

            group_nodes = []
            for group_index, group_chunks in enumerate(
                chunk_groups(chunks, chunk_group_size)
            ):
                fallback_summary = summarize_topic_chunks(
                    topic,
                    group_chunks,
                    group_index,
                )
                summary = await _summarize_chunks(
                    fallback_summary=fallback_summary,
                    title=f"主题分组摘要：{topic} #{group_index + 1}",
                    topic_hint=topic,
                    chunks=group_chunks,
                    with_llm_summary=with_llm_summary,
                )
                group_node = await _upsert_memory_node(
                    session,
                    tree_type="topic",
                    level=1,
                    key=topic_group_key(topic, group_index),
                    title=f"主题分组摘要：{topic} #{group_index + 1}",
                    summary=summary,
                    dense_embedding=await _embed_summary(summary, with_embedding),
                    metadata_={
                        "topic": topic,
                        "group_index": group_index,
                        "chunk_count": len(group_chunks),
                    },
                )
                group_nodes.append(group_node)

                for chunk in group_chunks:
                    session.add(
                        MemoryEdge(
                            parent_node_id=group_node.id,
                            chunk_id=chunk.id,
                            relation_type="contains",
                            weight=1.0,
                        )
                    )
                    stats.edges += 1

            fallback_root_summary = summarize_topic_nodes(topic, group_nodes)
            root_summary = await _summarize_nodes(
                fallback_summary=fallback_root_summary,
                title=f"主题概览：{topic}",
                topic_hint=topic,
                child_nodes=group_nodes,
                with_llm_summary=with_llm_summary,
            )
            root_node = await _upsert_memory_node(
                session,
                tree_type="topic",
                level=2,
                key=topic_root_key(topic),
                title=f"主题概览：{topic}",
                summary=root_summary,
                dense_embedding=await _embed_summary(root_summary, with_embedding),
                metadata_={
                    "topic": topic,
                    "source": "chunk.metadata_.topics"
                    if topic in explicit_topic_chunks
                    else "user_interests",
                    "group_count": len(group_nodes),
                    "chunk_count": len(chunks),
                },
            )

            for group_node in group_nodes:
                session.add(
                    MemoryEdge(
                        parent_node_id=root_node.id,
                        child_node_id=group_node.id,
                        relation_type="summarizes",
                        weight=1.0,
                    )
                )
                stats.edges += 1

            stats.topics += 1
            stats.topic_groups += len(group_nodes)

        await session.commit()

    return stats


def merge_stats(*items: BuildStats) -> BuildStats:
    """合并多个构建步骤的统计结果。"""
    merged = BuildStats()
    for item in items:
        merged.documents += item.documents
        merged.source_roots += item.source_roots
        merged.topics += item.topics
        merged.topic_groups += item.topic_groups
        merged.edges += item.edges
        merged.skipped_empty_documents += item.skipped_empty_documents
        merged.skipped_empty_topics += item.skipped_empty_topics
    return merged


async def main() -> None:
    parser = argparse.ArgumentParser(description="构建 Memory Tree")
    parser.add_argument("--document-id", help="只重建指定 document_id 的 Source Tree")
    parser.add_argument(
        "--tree",
        choices=["source", "topic", "all"],
        default="source",
        help="选择构建哪类树；默认保持旧行为，只构建 Source Tree",
    )
    parser.add_argument(
        "--with-embedding",
        action="store_true",
        help="为摘要节点生成 embedding；首次运行可能加载 bge-m3 模型",
    )
    parser.add_argument(
        "--no-llm-summary",
        action="store_true",
        help="关闭 LLM 摘要，使用抽取式兜底摘要",
    )
    args = parser.parse_args()
    with_llm_summary = not args.no_llm_summary

    if args.tree == "source":
        stats = await build_source_tree(
            document_id=args.document_id,
            with_embedding=args.with_embedding,
            with_llm_summary=with_llm_summary,
        )
    elif args.tree == "topic":
        stats = await build_topic_tree(
            with_embedding=args.with_embedding,
            with_llm_summary=with_llm_summary,
        )
    else:
        stats = merge_stats(
            await build_source_tree(
                document_id=args.document_id,
                with_embedding=args.with_embedding,
                with_llm_summary=with_llm_summary,
            ),
            await build_topic_tree(
                with_embedding=args.with_embedding,
                with_llm_summary=with_llm_summary,
            ),
        )
    print(json.dumps(asdict(stats), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
