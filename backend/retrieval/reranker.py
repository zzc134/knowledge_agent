"""LLM 重排：用 LLM 对候选文档打分（1-5）+ 给理由"""

import json
from config import get_settings

settings = get_settings()


async def llm_rerank(
    query: str,
    candidates: list[dict],
    llm_call,
    top_k: int | None = None,
) -> list[dict]:
    """用 LLM 对候选文档打分重排"""
    if top_k is None:
        top_k = settings.final_top_k

    if not candidates:
        return []

    candidates_text = ""
    for i, c in enumerate(candidates):
        candidates_text += f"[{i}] {c['content'][:300]}\n\n"

    system_prompt = (
        "你是一个检索质量评估器。根据用户问题，对每篇候选文档的相关性打分（1-5分）"
        "并给一句话理由，只返回 JSON 数组，格式：\n"
        '[{"index": 0, "score": 4, "reason": "直接回答了问题"}, ...]'
    )
    user_message = f"用户问题: {query}\n\n候选文档:\n{candidates_text}"

    response = await llm_call(system_prompt, user_message)

    try:
        scores = json.loads(response)
    except json.JSONDecodeError:
        return candidates[:top_k]

    score_map = {s["index"]: s for s in scores}
    reranked = []
    for i, c in enumerate(candidates):
        if i in score_map:
            c["rerank_score"] = score_map[i]["score"]
            c["rerank_reason"] = score_map[i]["reason"]
            reranked.append(c)

    reranked.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
    return reranked[:top_k]
