"""Memory Tree 检索评估脚本。

用法：
    cd backend
    python eval/eval_memory_tree_retriever.py "Agent Memory 怎么设计"

脚本会先确保 Source Tree 已构建，再执行 Tree Retrieval。
"""

import sys
sys.path.insert(0, ".")

import argparse
import asyncio

from db.database import init_db
import db.models
from memory.tree_builder import build_source_tree
from memory.tree_retriever import retrieve_from_memory_tree


async def main() -> None:
    parser = argparse.ArgumentParser(description="评估 Memory Tree 检索效果")
    parser.add_argument("query", nargs="?", default="Agent Memory 怎么设计")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--max-chunks", type=int, default=5)
    parser.add_argument("--use-embedding", action="store_true")
    args = parser.parse_args()

    await init_db()
    await build_source_tree(with_embedding=args.use_embedding)

    results = await retrieve_from_memory_tree(
        args.query,
        top_k=args.top_k,
        max_chunks=args.max_chunks,
        tree_type="source",
        use_embedding=args.use_embedding,
    )

    print(f"查询: {args.query}")
    print(f"结果组数: {len(results)}")

    for index, result in enumerate(results, start=1):
        print(f"\n--- 结果 {index} ---")
        print(
            f"命中节点: [{result.matched_node.tree_type} L{result.matched_node.level}] "
            f"{result.matched_node.title}"
        )
        print("摘要路径:")
        for node in result.memory_path:
            print(f"  - L{node.level} {node.title}")

        print("原始 chunks:")
        for chunk in result.chunks:
            preview = " ".join(chunk.content.split())[:160]
            print(f"  - chunk {chunk.chunk_index}: {preview}")


if __name__ == "__main__":
    asyncio.run(main())
