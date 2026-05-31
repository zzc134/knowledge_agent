"""Agent 间消息通信总线——每个 Agent 有独立收件箱，支持点对点和广播"""

import asyncio
from collections import defaultdict


class MessageBus:
    """Agent 间消息通信总线"""

    def __init__(self):
        self._inboxes: dict[str, asyncio.Queue] = defaultdict(asyncio.Queue)
        self._history: list[dict] = []
        self._listeners: list[callable] = []

    def register(self, agent_name: str) -> None:
        """注册一个 Agent 的收件箱"""
        self._inboxes[agent_name] = asyncio.Queue()

    async def send(
        self,
        from_agent: str,
        to_agent: str,
        msg_type: str,
        content: str,
        data: dict | None = None,
        round_num: int = 0,
    ) -> None:
        """向指定 Agent 发消息"""
        msg = {
            "from_agent": from_agent,
            "to_agent": to_agent,
            "msg_type": msg_type,
            "content": content,
            "data": data,
            "round_num": round_num,
        }
        self._history.append(msg)
        await self._inboxes[to_agent].put(msg)

        for listener in self._listeners:
            await listener(msg)

    async def broadcast(
        self,
        from_agent: str,
        msg_type: str,
        content: str,
        data: dict | None = None,
        round_num: int = 0,
    ) -> None:
        """向所有已注册 Agent 广播消息"""
        for name in self._inboxes:
            if name != from_agent:
                await self.send(from_agent, name, msg_type, content, data, round_num)

    async def receive(self, agent_name: str, timeout: float | None = None) -> dict:
        """从收件箱取一条消息（阻塞等待）"""
        if timeout:
            return await asyncio.wait_for(
                self._inboxes[agent_name].get(), timeout=timeout
            )
        return await self._inboxes[agent_name].get()

    def get_history(self) -> list[dict]:
        """获取完整通信历史"""
        return self._history

    def add_listener(self, callback: callable) -> None:
        """注册 SSE 监听器"""
        self._listeners.append(callback)
