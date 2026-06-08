"""Chunk 级 topic 自动抽取。

每个 chunk 单独调用 LLM 生成 topic，并用 asyncio 并发执行。
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from .topics import normalize_topics

TopicLLMCall = Callable[..., Awaitable[str]]


def parse_topics_response(response: str) -> list[str]:
    """把 LLM 返回解析成 topic 列表。

    优先支持 JSON 数组；如果模型返回普通文本，就按逗号、顿号、换行拆分。
    """
    text = response.strip()
    if not text:
        return []

    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return normalize_topics([str(item) for item in parsed])
        if isinstance(parsed, dict):
            raw_topics = parsed.get("topics") or parsed.get("topic") or []
            if isinstance(raw_topics, str):
                raw_topics = [raw_topics]
            return normalize_topics([str(item) for item in raw_topics])
    except json.JSONDecodeError:
        pass

    # 兜底：模型可能返回 "agent memory, rag, memory tree" 或逐行列表。
    text = re.sub(r"^[\s\-*\d.]+", "", text, flags=re.MULTILINE)
    parts = re.split(r"[,，、\n;；]+", text)
    return normalize_topics(parts)


async def extract_chunk_topics(
    *,
    title: str,
    chunk_content: str,
    seed_topics: list[str] | None = None,
    llm_call_func: TopicLLMCall | None = None,
) -> list[str]:
    """为单个 chunk 抽取 topic。

    seed_topics 是调用方传入的文档级先验；LLM 结果会和它合并。
    LLM 失败时直接返回 seed_topics，保证入库流程不中断。
    """
    normalized_seed_topics = normalize_topics(seed_topics)
    if llm_call_func is None:
        from core.llm import llm_call

        llm_call_func = llm_call

    system_prompt = (
        "你是知识库主题标注器。请为给定 chunk 提取 1-5 个简短 topic。"
        "topic 应该适合做检索标签，优先使用英文或稳定技术名词。"
        "只返回 JSON 数组，不要解释。"
    )
    user_message = f"""文档标题：{title}

已有文档级主题先验：{normalized_seed_topics}

chunk 内容：
{chunk_content[:2000]}

请返回 JSON 数组，例如 ["agent memory", "rag"]："""

    try:
        response = await llm_call_func(
            system_prompt=system_prompt,
            user_message=user_message,
        )
        llm_topics = parse_topics_response(response)
    except Exception:
        llm_topics = []

    return normalize_topics([*normalized_seed_topics, *llm_topics])[:8]


async def extract_topics_for_chunks(
    *,
    title: str,
    chunks: list[dict[str, Any]],
    seed_topics: list[str] | None = None,
    llm_call_func: TopicLLMCall | None = None,
    max_concurrency: int = 5,
) -> list[list[str]]:
    """并发为多个 chunks 抽取 topic。

    返回顺序和 chunks 输入顺序一致，方便 loader 写回对应 chunk metadata。
    """
    semaphore = asyncio.Semaphore(max(1, max_concurrency))

    async def run_one(chunk: dict[str, Any]) -> list[str]:
        async with semaphore:
            return await extract_chunk_topics(
                title=title,
                chunk_content=str(chunk.get("content", "")),
                seed_topics=seed_topics,
                llm_call_func=llm_call_func,
            )

    return await asyncio.gather(*(run_one(chunk) for chunk in chunks))
