"""
Agent 质量评估：来源标注率、矛盾检测率、回答相关性
"""
import sys
sys.path.insert(0, ".")

import asyncio
import json
from core.llm import llm_call
from retrieval.retriever import retrieve


async def evaluate_source_citation(response: str) -> dict:
    """评估回答是否标注了来源"""
    has_source = "[来源" in response or "[来源1]" in response or "来源:" in response
    return {
        "metric": "source_citation",
        "passed": has_source,
        "detail": "回答包含来源标注" if has_source else "缺少来源标注",
    }


async def evaluate_contradiction_handling(response: str) -> dict:
    """评估是否标注了信息矛盾"""
    has_conflict_mark = "冲突" in response or "矛盾" in response or "⚠️" in response
    return {
        "metric": "contradiction_handling",
        "passed": has_conflict_mark,
        "detail": "标注了信息冲突" if has_conflict_mark else "未标注冲突（或无不一致信息）",
    }


async def evaluate_relevance(query: str, response: str) -> dict:
    """用 LLM 评估回答与问题的相关性（1-5 分）"""
    prompt = f"""评估以下回答与用户问题的相关性，只返回一个 1-5 的分数和一句话理由。
JSON 格式：{{"score": 4, "reason": "..."}}

用户问题：{query}
回答：{response[:500]}"""

    result = await llm_call(
        system_prompt="你是检索质量评估专家，只返回 JSON。",
        user_message=prompt,
    )
    try:
        data = json.loads(result)
        return {
            "metric": "relevance",
            "score": data.get("score", 0),
            "reason": data.get("reason", ""),
        }
    except json.JSONDecodeError:
        return {"metric": "relevance", "score": 0, "reason": "解析失败"}


async def evaluate_agent_response(
    query: str, response: str, expected_citations: int = 1
) -> dict:
    """综合评估 Agent 回答质量"""
    source_result = await evaluate_source_citation(response)
    conflict_result = await evaluate_contradiction_handling(response)
    relevance_result = await evaluate_relevance(query, response)

    return {
        "query": query[:100],
        "response": response[:300],
        "source_cited": source_result["passed"],
        "contradiction_marked": conflict_result["passed"],
        "relevance_score": relevance_result.get("score", 0),
        "relevance_reason": relevance_result.get("reason", ""),
    }


async def main():
    """跑 Agent 评估"""
    test_cases_file = "eval/agent_test_cases.json"
    try:
        with open(test_cases_file) as f:
            test_cases = json.load(f)
    except FileNotFoundError:
        print(f"测试用例文件 {test_cases_file} 不存在，使用默认用例")

        test_cases = [
            {
                "query": "什么是混合检索？",
                "expected_citations": 1,
            },
            {
                "query": "如何设计 Agent 的记忆系统？",
                "expected_citations": 2,
            },
        ]

    print("Agent 质量评估")
    print("=" * 50)

    total_sources = 0
    total_conflicts = 0
    total_relevance = 0.0
    count = 0

    for case in test_cases:
        query = case["query"]
        print(f"\n评估: {query[:80]}...")

        # 先检索再生成回答
        try:
            results = await retrieve(query, llm_call, top_k=3)
            docs_text = "\n\n".join(
                f"[来源{i+1}] {r['content'][:300]}" for i, r in enumerate(results)
            )
            answer_prompt = f"基于以下检索结果回答，标注来源：\n{docs_text}\n\n问题：{query}"
            response = await llm_call(
                system_prompt="基于检索结果回答，标注来源编号，如有不一致请标注。",
                user_message=answer_prompt,
            )

            eval_result = await evaluate_agent_response(
                query, response, case.get("expected_citations", 1)
            )

            print(f"  来源标注: {'✅' if eval_result['source_cited'] else '❌'}")
            print(f"  矛盾标注: {'✅' if eval_result['contradiction_marked'] else 'N/A'}")
            print(f"  相关性评分: {eval_result['relevance_score']}/5")
            print(f"  理由: {eval_result['relevance_reason'][:100]}")

            if eval_result['source_cited']:
                total_sources += 1
            if eval_result['contradiction_marked']:
                total_conflicts += 1
            total_relevance += eval_result['relevance_score']
            count += 1

        except Exception as e:
            print(f"  评估失败: {e}")

    if count > 0:
        print("\n" + "=" * 50)
        print(f"总测试数: {count}")
        print(f"来源标注率: {total_sources / count:.1%}")
        print(f"矛盾检测率: {total_conflicts / count:.1%}")
        print(f"平均相关性: {total_relevance / count:.2f}/5")
        print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
