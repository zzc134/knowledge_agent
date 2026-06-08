"""Memory Tree 查询 API 逻辑。

这里不放 FastAPI 路由装饰器，只放可测试的查询函数。
main.py 负责把这些函数暴露成 HTTP 接口。
"""

from sqlalchemy import select

from db.database import async_session
from db.models import Chunk, MemoryEdge, MemoryNode


def serialize_memory_node(node: MemoryNode) -> dict:
    """把 MemoryNode 转成前端/API 友好的 dict。"""
    return {
        "id": node.id,
        "tree_type": node.tree_type,
        "level": node.level,
        "key": node.key,
        "title": node.title,
        "summary": node.summary,
        "metadata": node.metadata_ or {},
        "created_at": node.created_at.isoformat() if node.created_at else None,
        "updated_at": node.updated_at.isoformat() if node.updated_at else None,
    }


def serialize_chunk(chunk: Chunk) -> dict:
    """把 Chunk 转成前端/API 友好的 dict。"""
    return {
        "id": chunk.id,
        "document_id": chunk.document_id,
        "chunk_index": chunk.chunk_index,
        "content": chunk.content,
        "metadata": chunk.metadata_ or {},
        "created_at": chunk.created_at.isoformat() if chunk.created_at else None,
    }


async def list_memory_tree_roots(
    tree_type: str | None = None,
    level: int = 2,
    limit: int = 100,
) -> dict:
    """列出 Memory Tree 的高层节点，默认返回 L2 roots。"""
    stmt = select(MemoryNode).where(MemoryNode.level == level)
    if tree_type:
        stmt = stmt.where(MemoryNode.tree_type == tree_type)
    stmt = stmt.order_by(MemoryNode.tree_type, MemoryNode.key).limit(limit)

    async with async_session() as session:
        result = await session.execute(stmt)
        nodes = result.scalars().all()

    return {
        "nodes": [serialize_memory_node(node) for node in nodes],
        "count": len(nodes),
    }


async def get_memory_tree_node(node_id: str) -> dict:
    """查看一个节点的直接子节点和直接 chunks。"""
    async with async_session() as session:
        node = await session.get(MemoryNode, node_id)
        if node is None:
            return {"node": None, "child_nodes": [], "chunks": []}

        edge_result = await session.execute(
            select(MemoryEdge)
            .where(MemoryEdge.parent_node_id == node_id)
            .order_by(MemoryEdge.weight.desc(), MemoryEdge.created_at)
        )
        edges = edge_result.scalars().all()

        child_node_ids = [edge.child_node_id for edge in edges if edge.child_node_id]
        chunk_ids = [edge.chunk_id for edge in edges if edge.chunk_id]

        child_nodes = []
        if child_node_ids:
            child_result = await session.execute(
                select(MemoryNode)
                .where(MemoryNode.id.in_(child_node_ids))
                .order_by(MemoryNode.level.desc(), MemoryNode.key)
            )
            child_nodes = child_result.scalars().all()

        chunks = []
        if chunk_ids:
            chunk_result = await session.execute(
                select(Chunk)
                .where(Chunk.id.in_(chunk_ids))
                .order_by(Chunk.chunk_index)
            )
            chunks = chunk_result.scalars().all()

    return {
        "node": serialize_memory_node(node),
        "child_nodes": [serialize_memory_node(child) for child in child_nodes],
        "chunks": [serialize_chunk(chunk) for chunk in chunks],
    }


async def search_memory_tree(
    query: str,
    tree_type: str | None = None,
    top_k: int = 5,
    max_chunks: int = 5,
) -> dict:
    """用 Tree Retriever 搜 Memory Tree，并返回摘要路径和 chunks。"""
    from memory.tree_retriever import retrieve_from_memory_tree, results_to_dict

    results = await retrieve_from_memory_tree(
        query,
        top_k=top_k,
        max_chunks=max_chunks,
        tree_type=tree_type,
    )
    return {
        "query": query,
        "results": results_to_dict(results),
        "count": len(results),
    }
