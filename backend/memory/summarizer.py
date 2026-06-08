"""Memory Tree 的 LLM 摘要生成器。

这里负责把原始 chunks 或子节点摘要压缩成更高层的语义摘要。
调用方仍然保留抽取式兜底，LLM 失败时不会阻断建树。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

LLMCall = Callable[..., Awaitable[str]]


def _compact(text: str, max_chars: int) -> str:
    """压缩输入，避免摘要 prompt 过长。"""
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "..."


async def summarize_chunks_with_llm(
    *,
    title: str,
    topic_hint: str,
    chunk_texts: list[str],
    llm_call_func: LLMCall | None = None,
) -> str:
    """把多个 L0 chunks 总结成一个 L1 摘要。"""
    if llm_call_func is None:
        from core.llm import llm_call

        llm_call_func = llm_call

    chunk_block = "\n\n".join(
        f"[chunk {index + 1}] {_compact(text, 900)}"
        for index, text in enumerate(chunk_texts[:8])
    )
    system_prompt = (
        "你是个人知识库的记忆摘要器。"
        "请把多个原始 chunk 压缩成一个适合 Memory Tree L1 节点使用的摘要。"
        "摘要要保留主题、关键事实、概念关系和可检索关键词。"
    )
    user_message = f"""标题：{title}
主题提示：{topic_hint}

原始 chunks：
{chunk_block}

请输出 120-250 字中文摘要。不要列无关套话。"""

    return (
        await llm_call_func(
            system_prompt=system_prompt,
            user_message=user_message,
        )
    ).strip()


async def summarize_nodes_with_llm(
    *,
    title: str,
    topic_hint: str,
    child_summaries: list[str],
    llm_call_func: LLMCall | None = None,
) -> str:
    """把多个 L1 摘要总结成一个 L2 概览摘要。"""
    if llm_call_func is None:
        from core.llm import llm_call

        llm_call_func = llm_call

    summary_block = "\n\n".join(
        f"[summary {index + 1}] {_compact(summary, 800)}"
        for index, summary in enumerate(child_summaries[:10])
    )
    system_prompt = (
        "你是个人知识库的高层记忆摘要器。"
        "请把多个子摘要合成为一个 Memory Tree L2 概览。"
        "概览应帮助 Agent 冷启动时快速理解这个来源或主题覆盖了什么。"
    )
    user_message = f"""节点标题：{title}
主题提示：{topic_hint}

子摘要：
{summary_block}

请输出 150-300 字中文概览，说明主要主题、关键关系和可下钻方向。"""

    return (
        await llm_call_func(
            system_prompt=system_prompt,
            user_message=user_message,
        )
    ).strip()
