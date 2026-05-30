"""上下文装配：分层装配，变化少的在前，保证 prefix cache 命中率最大"""


from memory.long_term import get_active_interests
from memory.short_term import ShortTermMemory
from config import get_settings



settings = get_settings()


async def assemble_context(
    agent_system_prompt: str,
    session: ShortTermMemory,
    tools_description: str = "",
    user_query: str = "",
    retrieved_docs: list[dict] | None = None,
) -> list[dict]:
    """
    分层装配上下文，顺序至关重要——变化少的在前，变化多的在后。
    排序原则：静态 > 低频更新 > 高频更新 > 每次不同
    """

    # 第 1 层：用户长期兴趣（低频更新）
    interests = await get_active_interests()
    qualified = [i for i in interests if i['confidence'] > 0.3]

    if qualified:
        interest_text = "## 用户长期兴趣\n"
        for i in qualified[:5]:
            interest_text += f"- {i['topic']} (置信度: {i['confidence']:.2f})\n"
    else:
        interest_text = "## 用户长期兴趣\n暂无记录\n"

    # 第 2 层：当前会话摘要（中频更新）
    session_text = f"## 当前会话上下文\n{session.get_recent_context()}"

    # 组装 system prompt
    full_system = f"{agent_system_prompt}\n\n{interest_text}\n{session_text}"
    messages = [{"role": "system", "content": full_system}]

    # 第 3 层：工具定义（几乎不变）
    if tools_description:
        messages.append({
            "role": "system",
            "content": f"## 可用工具\n{tools_description}",
        })

    # 第 4 层：检索结果（每次 query 不同）
    if retrieved_docs:
        docs_text = "## 检索结果\n"
        for i, doc in enumerate(retrieved_docs):
            docs_text += f"[{i}] {doc['content'][:300]}\n"
        messages.append({"role": "system", "content": docs_text})

    # 第 5 层：当前 query（每次都变）
    messages.append({"role": "user", "content": user_query})

    return messages
