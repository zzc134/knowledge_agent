"""短期记忆：会话级上下文管理，会话结束时触发摘要写入长期记忆"""

from datetime import datetime, timezone
from collections import deque
from config import get_settings

settings = get_settings()


class ShortTermMemory:
    """
    会话级短期记忆：追踪当前会话的对话、检索记录、阅读主题。
    每个会话创建一个实例，会话结束后销毁。
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.messages: deque[dict] = deque(maxlen=settings.short_term_max_rounds)
        self.retrieved_docs: list[str] = []   #记录检索过的
        self.accessed_topics: dict[str, int] = {}  #主题-访问次数

    def add_message(self, role: str, content: str) -> None:
        """记录一轮对话"""
        self.messages.append({
            "role": role,
            "content": content[:2000],
            "timestamp": datetime.now(timezone.utc).replace(tzinfo=None),
        })

    def add_retrieved(self, chunk_id: str) -> None:
        """记录检索过的文档"""
        if chunk_id not in self.retrieved_docs:
            self.retrieved_docs.append(chunk_id)

    def record_topic(self, topic: str) -> None:
        """记录访问了某个主题"""
        topic = topic.strip().lower()
        self.accessed_topics[topic] = self.accessed_topics.get(topic, 0) + 1

    def get_recent_context(self, n: int = 5) -> str:
        """获取最近 N 轮对话，用于拼接 context"""
        recent = list(self.messages)[-n:]
        return "\n".join(
            f"[{m['role']}]: {m['content'][:500]}" for m in recent
        )

    def get_top_topics(self, n: int = 5) -> list[str]:
        """获取本次会话访问最多的主题"""
        sorted_topics = sorted(
            self.accessed_topics.items(), key=lambda x: x[1], reverse=True
        )
        return [t for t, _ in sorted_topics[:n]]

    async def end_session(self) -> dict:
        """
        会话结束：汇总本次会话的关键信息，返回给上层。
        上层用这些数据决定是否写入 long_term。
        """
        return {
            "session_id": self.session_id,
            "message_count": len(self.messages),
            "top_topics": self.get_top_topics(),
            "retrieved_docs_count": len(self.retrieved_docs),
            "summary_needed": len(self.messages) >= settings.session_summary_trigger_rounds,
        }
