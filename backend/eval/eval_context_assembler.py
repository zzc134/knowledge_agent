"""验证上下文装配器包含长期兴趣、Memory Tree 和短期会话段。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncio

from context.assembler import assemble_context
from memory.short_term import ShortTermMemory


async def main() -> None:
    session = ShortTermMemory("eval-context")
    session.add_message("user", "我想了解 Agent Memory")
    session.add_message("editor", "我们可以从短期记忆和长期记忆开始。")

    messages = await assemble_context(
        agent_system_prompt="你是知识编辑。",
        session=session,
        tools_description="- answer_with_search: 搜索并回答",
        user_query="Agent Memory 怎么设计？",
        retrieved_docs=[{"content": "Agent 记忆系统包括短期记忆和长期记忆。"}],
    )

    system_prompt = messages[0]["content"]
    print(system_prompt)

    assert "## 用户长期兴趣" in system_prompt
    assert "## Memory Tree 相关摘要" in system_prompt
    assert "## 当前会话上下文" in system_prompt
    assert messages[-1]["role"] == "user"
    assert messages[-1]["content"] == "Agent Memory 怎么设计？"


if __name__ == "__main__":
    asyncio.run(main())
