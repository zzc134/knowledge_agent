"""Memory Tree 检索器。

第一版目标：让 Agent 可以先检索摘要节点，再沿 MemoryEdge 下钻到原始 chunks。

检索路径：
query -> memory_nodes -> memory_edges -> chunks
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import asdict, dataclass

from sqlalchemy import or_, select, text

from db.database import async_session
from db.models import Chunk, MemoryEdge, MemoryNode


@dataclass
class RetrievedMemoryNode:
    """返回给上层的摘要节点信息。"""

    id: str
    tree_type: str
    level: int
    key: str
    title: str
    summary: str


@dataclass
class RetrievedChunk:
    """返回给上层的原始 chunk 信息。"""

    chunk_id: str
    document_id: str
    chunk_index: int
    content: str


@dataclass
class MemoryTreeResult:
    """一次 Tree Retrieval 的结果。

    matched_node 是最先命中的摘要节点。
    memory_path 是从命中节点下钻经过的摘要节点。
    chunks 是最终取回的 L0 原始证据。
    """

    matched_node: RetrievedMemoryNode
    memory_path: list[RetrievedMemoryNode]
    chunks: list[RetrievedChunk]


def tokenize_query(query: str) -> list[str]:
    """把用户问题拆成关键词。

    英文、数字、下划线、短横线会按词拆；连续中文会保留为词组。
    第一版保持简单，后续可以接分词器或复用 embedding。
    """
    tokens = re.findall(r"[a-zA-Z0-9_:-]+|[\u4e00-\u9fff]{2,}", query.lower())
    seen = set()
    result = []
    for token in tokens:
        token = token.strip()
        if token and token not in seen:
            seen.add(token)
            result.append(token)
    return result


def serialize_node(node: MemoryNode) -> RetrievedMemoryNode:
    """把 ORM 节点转成稳定的返回结构。"""
    return RetrievedMemoryNode(
        id=node.id,
        tree_type=node.tree_type,
        level=node.level,
        key=node.key,
        title=node.title,
        summary=node.summary,
    )


def serialize_chunk(chunk: Chunk) -> RetrievedChunk:
    """把 ORM chunk 转成稳定的返回结构。"""
    return RetrievedChunk(
        chunk_id=chunk.id,
        document_id=chunk.document_id,
        chunk_index=chunk.chunk_index,
        content=chunk.content,
    )


#通过关键词匹配进行摘要节点打分
def _keyword_score(node: MemoryNode, tokens: list[str]) -> float:
    """给关键词命中的摘要节点做一个简单排序分。

    title/key 命中比 summary 命中更重要，因为它们通常更接近主题标签。
    level 越高越靠前，方便先看概览。
    """
    haystacks = {
        "title": node.title.lower(),
        "key": node.key.lower(),
        "summary": node.summary.lower(),
    }
    score = 0.0
    for token in tokens:
        if token in haystacks["title"]:
            score += 3.0
        if token in haystacks["key"]:
            score += 2.0
        if token in haystacks["summary"]:
            score += 1.0
    score += node.level * 0.1
    return score


async def search_memory_nodes_by_keyword(
    query: str,
    *,
    top_k: int = 5,
    tree_type: str | None = None,
) -> list[MemoryNode]:
    """用关键词检索 memory_nodes。

    这是没有摘要 embedding 时的本地兜底检索方式。
    """
    tokens = tokenize_query(query)
    if not tokens:
        return []

    conditions = []
    for token in tokens[:8]:
        pattern = f"%{token}%"
        conditions.append(MemoryNode.title.ilike(pattern))
        conditions.append(MemoryNode.key.ilike(pattern))
        conditions.append(MemoryNode.summary.ilike(pattern))

    stmt = select(MemoryNode).where(or_(*conditions))
    if tree_type:
        stmt = stmt.where(MemoryNode.tree_type == tree_type)

    async with async_session() as session:
        result = await session.execute(stmt.limit(top_k * 5))
        nodes = result.scalars().all()

    ranked = sorted(nodes, key=lambda node: _keyword_score(node, tokens), reverse=True)
    return ranked[:top_k]


async def search_memory_nodes_by_embedding(
    query: str,
    *,
    top_k: int = 5,
    tree_type: str | None = None,
) -> list[MemoryNode]:
    """用摘要 embedding 检索 memory_nodes。

    只有在 tree_builder 使用 --with-embedding 构建过节点时才有结果。
    """
    from ingestion.embedder import embed_text

    query_embedding = embed_text(query)
    vec_str = "'[" + ",".join(map(str, query_embedding)) + "]'::vector"

    where_clause = "dense_embedding IS NOT NULL"
    params = {}
    if tree_type:
        where_clause += " AND tree_type = :tree_type"
        params["tree_type"] = tree_type

    async with async_session() as session:
        result = await session.execute(
            text(
                f"""
                SELECT id
                FROM memory_nodes
                WHERE {where_clause}
                ORDER BY dense_embedding <=> {vec_str}
                LIMIT :top_k
                """
            ),
            {**params, "top_k": top_k},
        )
        ids = [row[0] for row in result.fetchall()]
        if not ids:
            return []

        nodes_by_id = {
            node.id: node
            for node in (
                await session.execute(select(MemoryNode).where(MemoryNode.id.in_(ids)))
            )
            .scalars()
            .all()
        }

    return [nodes_by_id[node_id] for node_id in ids if node_id in nodes_by_id]


async def _collect_from_node(
    session,
    node: MemoryNode,
    *,
    max_chunks: int,
    path: list[RetrievedMemoryNode],
    chunks: list[RetrievedChunk],
    seen_node_ids: set[str],
    seen_chunk_ids: set[str],
) -> None:
    """从一个摘要节点递归下钻到 chunks。

    MemoryEdge 支持 node -> node 和 node -> chunk 两种边，所以这里需要递归。
    """
    if node.id in seen_node_ids:
        return
    seen_node_ids.add(node.id)
    path.append(serialize_node(node))

    edge_result = await session.execute(
        select(MemoryEdge)
        .where(MemoryEdge.parent_node_id == node.id)
        .order_by(MemoryEdge.weight.desc(), MemoryEdge.created_at)
    )
    edges = edge_result.scalars().all()

    for edge in edges:
        if len(chunks) >= max_chunks:
            return

        if edge.chunk_id:
            chunk = await session.get(Chunk, edge.chunk_id)
            if chunk and chunk.id not in seen_chunk_ids:
                seen_chunk_ids.add(chunk.id)
                chunks.append(serialize_chunk(chunk))

        if edge.child_node_id:
            child_node = await session.get(MemoryNode, edge.child_node_id)
            if child_node:
                await _collect_from_node(
                    session,
                    child_node,
                    max_chunks=max_chunks,
                    path=path,
                    chunks=chunks,
                    seen_node_ids=seen_node_ids,
                    seen_chunk_ids=seen_chunk_ids,
                )


async def expand_memory_node(
    node: MemoryNode,
    *,
    max_chunks: int = 5,
) -> MemoryTreeResult:
    """把一个命中的摘要节点展开成摘要路径和原始 chunks。"""
    async with async_session() as session:
        attached_node = await session.get(MemoryNode, node.id)
        if attached_node is None:
            raise ValueError(f"MemoryNode not found: {node.id}")

        path: list[RetrievedMemoryNode] = []
        chunks: list[RetrievedChunk] = []
        await _collect_from_node(
            session,
            attached_node,
            max_chunks=max_chunks,
            path=path,
            chunks=chunks,
            seen_node_ids=set(),
            seen_chunk_ids=set(),
        )

    return MemoryTreeResult(
        matched_node=serialize_node(node),
        memory_path=path,
        chunks=chunks,
    )


async def retrieve_from_memory_tree(
    query: str,
    *,
    top_k: int = 3,
    max_chunks: int = 5,
    tree_type: str | None = None,
    use_embedding: bool = False,
) -> list[MemoryTreeResult]:
    """从 Memory Tree 检索相关摘要节点并下钻到原始 chunks。"""
    if use_embedding:
        nodes = await search_memory_nodes_by_embedding(
            query,
            top_k=top_k,
            tree_type=tree_type,
        )
        if not nodes:
            nodes = await search_memory_nodes_by_keyword(
                query,
                top_k=top_k,
                tree_type=tree_type,
            )
    else:
        nodes = await search_memory_nodes_by_keyword(
            query,
            top_k=top_k,
            tree_type=tree_type,
        )

    results = []
    for node in nodes:
        expanded = await expand_memory_node(node, max_chunks=max_chunks)
        if expanded.chunks:
            results.append(expanded)

    return results


def results_to_dict(results: list[MemoryTreeResult]) -> list[dict]:
    """把 dataclass 结果转成 JSON 友好的 dict。"""
    return [asdict(result) for result in results]


async def main() -> None:
    parser = argparse.ArgumentParser(description="从 Memory Tree 检索并下钻到 chunks")
    parser.add_argument("query", help="用户查询")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--max-chunks", type=int, default=5)
    parser.add_argument("--tree-type", choices=["source", "topic", "global"])
    parser.add_argument("--use-embedding", action="store_true")
    args = parser.parse_args()

    results = await retrieve_from_memory_tree(
        args.query,
        top_k=args.top_k,
        max_chunks=args.max_chunks,
        tree_type=args.tree_type,
        use_embedding=args.use_embedding,
    )
    print(json.dumps(results_to_dict(results), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
