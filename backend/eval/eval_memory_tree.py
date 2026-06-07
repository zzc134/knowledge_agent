"""Memory Tree 构建评估脚本。

用法：
    cd backend
    python eval/eval_memory_tree.py

脚本会构建 Source Tree，并输出 memory_nodes / memory_edges 的基础统计。
"""

import sys
sys.path.insert(0, ".")

import asyncio
from collections import Counter

from sqlalchemy import select

from db.database import async_session, init_db
import db.models
from db.models import MemoryEdge, MemoryNode
from memory.tree_builder import build_source_tree


async def count_memory_tree() -> None:
    """输出当前 Memory Tree 的节点和边统计。"""
    async with async_session() as session:
        node_result = await session.execute(select(MemoryNode))
        nodes = node_result.scalars().all()

        edge_result = await session.execute(select(MemoryEdge))
        edges = edge_result.scalars().all()

    by_tree_and_level = Counter((node.tree_type, node.level) for node in nodes)
    by_relation = Counter(edge.relation_type for edge in edges)

    print("\n--- Memory Tree 统计 ---")
    print(f"节点总数: {len(nodes)}")
    for (tree_type, level), count in sorted(by_tree_and_level.items()):
        print(f"  {tree_type} L{level}: {count}")

    print(f"边总数: {len(edges)}")
    for relation_type, count in sorted(by_relation.items()):
        print(f"  {relation_type}: {count}")

    print("\n--- 示例节点 ---")
    for node in nodes[:5]:
        print(f"  [{node.tree_type} L{node.level}] {node.key} -> {node.title}")


async def main() -> None:
    await init_db()

    print("--- 构建 Source Tree ---")
    stats = await build_source_tree()
    print(f"处理文档数: {stats.documents}")
    print(f"来源根节点数: {stats.source_roots}")
    print(f"新增关系边数: {stats.edges}")
    print(f"跳过空文档数: {stats.skipped_empty_documents}")

    await count_memory_tree()


if __name__ == "__main__":
    asyncio.run(main())
