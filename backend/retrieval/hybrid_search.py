"""混合检索：Dense (pgvector cosine) + Sparse (tsvector) + RRF 融合"""

from sqlalchemy import text
from db.database import async_session
from config import get_settings

settings = get_settings()


async def dense_search(query_embedding: list[float], top_k: int | None = None) -> list[dict]:
    """Dense 通路：pgvector 余弦相似度检索"""
    if top_k is None:
        top_k = settings.dense_top_k

    vec_str = "'[" + ",".join(map(str, query_embedding)) + "]'::vector"

    async with async_session() as session:
        result = await session.execute(
            text(f"""
                SELECT c.id, c.content, c.document_id, c.chunk_index,
                       1 - (c.dense_embedding <=> {vec_str}) AS similarity
                FROM chunks c
                WHERE c.dense_embedding IS NOT NULL
                ORDER BY c.dense_embedding <=> {vec_str}
                LIMIT {top_k}
            """)
        )
        rows = result.fetchall()

    return [
        {
            "chunk_id": r[0],
            "content": r[1],
            "document_id": r[2],
            "chunk_index": r[3],
            "score": float(r[4]),
        }
        for r in rows
    ]


async def sparse_search(query_text: str, top_k: int | None = None) -> list[dict]:
    """Sparse 通路：PostgreSQL tsvector 全文检索"""
    if top_k is None:
        top_k = settings.sparse_top_k

    escaped_query = query_text.replace("'", "''")

    async with async_session() as session:
        result = await session.execute(
            text(f"""
                SELECT c.id, c.content, c.document_id, c.chunk_index,
                       ts_rank(c.tsv::tsvector, query) AS rank
                FROM chunks c,
                     plainto_tsquery('simple', '{escaped_query}') AS query
                WHERE c.tsv::tsvector @@ query
                ORDER BY rank DESC
                LIMIT {top_k}
            """)
        )
        rows = result.fetchall()

    return [
        {
            "chunk_id": r[0],
            "content": r[1],
            "document_id": r[2],
            "chunk_index": r[3],
            "score": float(r[4]),
        }
        for r in rows
    ]


def reciprocal_rank_fusion(
    dense_results: list[dict],
    sparse_results: list[dict],
    k: int | None = None,
) -> list[dict]:
    """
    RRF 融合：dense + sparse 两路排名加权合并去重。
    只用排名不用绝对值，天然适合异构检索结果融合。
    """
    if k is None:
        k = settings.rrf_k

    rrf_scores: dict[str, float] = {}
    content_map: dict[str, dict] = {}

    for rank, item in enumerate(dense_results, start=1):
        cid = item['chunk_id']
        rrf_scores[cid] = rrf_scores.get(cid, 0) + 1.0 / (k + rank)
        content_map[cid] = item

    for rank, item in enumerate(sparse_results, start=1):
        cid = item["chunk_id"]
        rrf_scores[cid] = rrf_scores.get(cid, 0) + 1.0 / (k + rank)
        content_map[cid] = item

    sorted_ids = sorted(rrf_scores, key=rrf_scores.get, reverse=True)
    fused = []
    for cid in sorted_ids:
        item = dict(content_map[cid])
        item['rrf_score'] = rrf_scores[cid]
        fused.append(item)

    return fused
