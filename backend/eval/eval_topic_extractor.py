"""验证 chunk 级 topic 自动抽取。

这个脚本不调用真实 LLM，用 fake llm 测试并发抽取和规范化逻辑。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncio

from ingestion.topic_extractor import extract_topics_for_chunks


async def fake_llm_call(system_prompt: str, user_message: str, **kwargs) -> str:
    """模拟 LLM：根据 chunk 内容返回不同 topic。"""
    await asyncio.sleep(0.01)
    if "短期记忆" in user_message:
        return '["Agent Memory", "Short Term Memory"]'
    if "Memory Tree" in user_message:
        return '["Agent Memory", "Memory Tree", "Topic Tree"]'
    return '["RAG"]'


async def main() -> None:
    chunks = [
        {"content": "短期记忆负责当前会话上下文。"},
        {"content": "Memory Tree 可以先读摘要再下钻 chunk。"},
    ]

    topics_by_chunk = await extract_topics_for_chunks(
        title="Agent Memory 设计指南",
        chunks=chunks,
        seed_topics=["RAG", "agent memory"],
        llm_call_func=fake_llm_call,
        max_concurrency=2,
    )

    print(topics_by_chunk)
    assert topics_by_chunk == [
        ["rag", "agent memory", "short term memory"],
        ["rag", "agent memory", "memory tree", "topic tree"],
    ]


if __name__ == "__main__":
    asyncio.run(main())
