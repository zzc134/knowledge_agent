"""检索编排：串联召回 → 融合 → 重排的完整流程"""

from .hybrid_search import dense_search, sparse_search, reciprocal_rank_fusion
from .reranker import llm_rerank
from ingestion.embedder import embed_text
from config import get_settings

settings = get_settings()


async def retrieve(
    query: str,
    llm_call,
    top_k: int | None = None,
) -> list[dict]:
    """
    完整检索链路：embedding → dense + sparse 双路召回 → RRF 融合 → LLM 重排
    """
    if top_k is None:
        top_k = settings.final_top_k

    query_embedding = embed_text(query)

    dense_results = await dense_search(query_embedding)
    sparse_results = await sparse_search(query)

    fused = reciprocal_rank_fusion(dense_results, sparse_results)

    reranked = await llm_rerank(query, fused, llm_call, top_k)

    return reranked
