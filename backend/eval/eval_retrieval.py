"""
检索质量评估：对比四种策略的 MRR / Hit Rate / NDCG
1. 纯 dense (pgvector cosine)
2. 纯 sparse (tsvector)
3. 混合检索（无重排）
4. 混合检索 + LLM 重排
"""
import sys
sys.path.insert(0, ".")

import asyncio
import json
import math
from retrieval.hybrid_search import dense_search, sparse_search, reciprocal_rank_fusion
from retrieval.reranker import llm_rerank
from ingestion.embedder import embed_text
from core.llm import llm_call


def load_test_queries(filepath: str = "eval/test_queries.json") -> list[dict]:
    with open(filepath) as f:
        return json.load(f)


def mrr(results: list[dict], relevant_id: str) -> float:
    """MRR: 正确答案排第几。排名越靠前得分越高。"""
    for rank, item in enumerate(results, start=1):
        if item['chunk_id'] == relevant_id:
            return 1.0 / rank
    return 0.0


def hit_rate_at_k(results: list[dict], relevant_id: str, k: int = 5) -> float:
    """HitRate@K: 正确答案是否在前 K 个结果中"""
    top_ids = {item['chunk_id'] for item in results[:k]}
    return 1.0 if relevant_id in top_ids else 0.0


def ndcg_at_k(results: list[dict], relevant_id: str, k: int = 5) -> float:
    """NDCG@K: 正确答案排得越靠前，得分越高"""
    for rank, item in enumerate(results[:k], start=1):
        if item['chunk_id'] == relevant_id:
            return 1.0 / math.log2(rank + 1)
    return 0.0


async def evaluate_strategy(
    name: str,
    test_queries: list[dict],
    dense_only: bool = False,
    sparse_only: bool = False,
    with_rerank: bool = False,
) -> dict:
    """跑一遍评估，返回各项指标均值"""
    total_mrr = 0.0
    total_hit = 0.0
    total_ndcg = 0.0

    for q in test_queries:
        query = q['query']
        relevant_id = q['relevant_chunk_id']

        if sparse_only:
            results = await sparse_search(query)
        elif dense_only:
            embedding = embed_text(query)
            results = await dense_search(embedding)
        else:
            embedding = embed_text(query)
            dense = await dense_search(embedding)
            sparse = await sparse_search(query)
            fused = reciprocal_rank_fusion(dense, sparse)
            if with_rerank:
                results = await llm_rerank(query, fused, llm_call)
            else:
                results = fused

        total_mrr += mrr(results, relevant_id)
        total_hit += hit_rate_at_k(results, relevant_id)
        total_ndcg += ndcg_at_k(results, relevant_id)

    n = len(test_queries)
    return {
        "strategy": name,
        "num_queries": n,
        "MRR": round(total_mrr / n, 4),
        "HitRate@5": round(total_hit / n, 4),
        "NDCG@5": round(total_ndcg / n, 4),
    }


async def main():
    """验证数据库里有数据后跑四种策略的对比"""
    from retrieval.hybrid_search import async_session
    from sqlalchemy import text

    async with async_session() as session:
        result = await session.execute(text("SELECT COUNT(*) FROM chunks"))
        count = result.scalar()
        print(f"知识库 chunk 总数: {count}")
        if count == 0:
            print("请先填充测试数据！")
            return

    test_queries = load_test_queries()
    print(f"测试查询数: {len(test_queries)}")

    results = []

    print("\n纯 Dense 检索...")
    results.append(await evaluate_strategy("dense_only", test_queries, dense_only=True))

    print("纯 Sparse 检索...")
    results.append(await evaluate_strategy("sparse_only", test_queries, sparse_only=True))

    print("混合检索（无重排）...")
    results.append(await evaluate_strategy("hybrid_no_rerank", test_queries))

    print("混合检索 + LLM 重排...")
    results.append(await evaluate_strategy("hybrid_rerank", test_queries, with_rerank=True))

    print("\n" + "=" * 60)
    print(f"{'策略':<25} {'MRR':<10} {'HitRate@5':<12} {'NDCG@5':<10}")
    print("-" * 60)
    for r in results:
        print(f"{r['strategy']:<25} {r['MRR']:<10} {r['HitRate@5']:<12} {r['NDCG@5']:<10}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
