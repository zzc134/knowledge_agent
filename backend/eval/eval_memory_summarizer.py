"""验证 Memory Tree LLM 摘要器。

不调用真实 LLM，用 fake llm 检查函数接口。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncio

from memory.summarizer import summarize_chunks_with_llm, summarize_nodes_with_llm


async def fake_llm_call(system_prompt: str, user_message: str, **kwargs) -> str:
    if "原始 chunks" in user_message:
        return "这是 L1 摘要：内容围绕 Agent Memory 的短期记忆、长期记忆和 Memory Tree。"
    return "这是 L2 概览：该主题覆盖 Agent 记忆系统、RAG 检索和可下钻的知识结构。"


async def main() -> None:
    l1 = await summarize_chunks_with_llm(
        title="Agent Memory 设计指南",
        topic_hint="agent memory",
        chunk_texts=["短期记忆负责会话。", "Memory Tree 负责层级摘要。"],
        llm_call_func=fake_llm_call,
    )
    l2 = await summarize_nodes_with_llm(
        title="主题概览：agent memory",
        topic_hint="agent memory",
        child_summaries=[l1],
        llm_call_func=fake_llm_call,
    )

    print(l1)
    print(l2)
    assert "L1 摘要" in l1
    assert "L2 概览" in l2


if __name__ == "__main__":
    asyncio.run(main())
