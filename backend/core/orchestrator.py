"""Agent 指挥中心——创建 Agent、注册到消息总线、协调协商回合"""

import asyncio
import hashlib
import re
from core.message_bus import MessageBus
from agents.collector import CollectorAgent
from agents.curator import CuratorAgent
from agents.librarian import LibrarianAgent
from agents.editor import EditorAgent
from memory.short_term import ShortTermMemory


class Orchestrator:
    """多 Agent 协商协调器"""

    def __init__(self):
        self.bus = MessageBus()
        self.collector = CollectorAgent()
        self.curator = CuratorAgent(message_bus=self.bus)
        self.librarian = LibrarianAgent()
        self.editor = EditorAgent()
        self.session: ShortTermMemory | None = None

        for name in ["collector", "curator", "librarian", "editor"]:
            self.bus.register(name)

    def new_session(self, session_id: str) -> None:
        """创建一个新的会话"""
        self.session = ShortTermMemory(session_id)
        self.editor.session = self.session

    async def route_and_execute(self, user_message: str) -> dict:
        """用户消息入口——启动多 Agent 并发协商"""
        if self.session is None:
            self.new_session("default")

        self.session.add_message("user", user_message)
        result = await self._run_concurrent_negotiation(user_message)

        response_text = result.get("final_answer", str(result))
        agent_used = result.get("primary_agent", "editor")

        self.session.add_message(agent_used, response_text)

        from memory.long_term import record_access, check_auto_capture

        for topic in self.session.get_top_topics(3):
            await record_access(topic)
            await check_auto_capture(topic)

        return {
            "agent": agent_used,
            "response": response_text,
            "tool_calls": result.get("tool_calls", []),
            "session_id": self.session.session_id,
        }

    async def _run_concurrent_negotiation(self, user_message: str) -> dict:
        """并发多 Agent 协商：每个 Agent 收到任务后自主决定做什么、对谁说话"""
        is_url = "http://" in user_message or "https://" in user_message

        if is_url:
            hint = (
                "@collector：抓取此URL并入库\n"
                "@curator：等Collector完成后评估内容质量\n"
                "@librarian：入库后检索相关内容\n"
                "@editor：准备综合回答"
            )
        else:
            hint = (
                "@librarian：检索相关内容并告知 @editor 和 @curator\n"
                "@editor：收到检索结果后综合回答用户\n"
                "@curator：记录本次检索的主题\n"
                "@collector：如果与抓取无关可忽略"
            )
        await self.bus.broadcast(
            "orchestrator", "proposal",
            f"用户消息：{user_message}\n\n各Agent职责提醒：\n{hint}",
            round_num=0,
        )

        #谁负责回答用户
        primary = "collector" if is_url else "editor"

        final_answer = None
        tool_calls_log = []
        #seen用来MD5集合，防止同一个消息被利用
        seen = set()
        #round协商轮数
        rounds = 0
        #quiet_rounds安静的轮数
        quiet_rounds = 0
        max_rounds = 20
        max_quiet = 8

        agent_map = {
            "librarian": self.librarian,
            "editor": self.editor,
            "curator": self.curator,
            "collector": self.collector,
        }

        while rounds < max_rounds and quiet_rounds < max_quiet:
            rounds += 1

            msgs_by_agent: list[tuple[str, dict]] = []
            for name in agent_map:
                try:
                    msg = await self.bus.receive(name, timeout=3)
                    #md5(来判断是否是同一个消息，来源相同，message想通就是一个消息，就屏蔽调
                    key = hashlib.md5(
                        (msg.get("content", "") + msg.get("from_agent", "")).encode()
                    ).hexdigest()
                    if key not in seen:
                        seen.add(key)
                        msgs_by_agent.append((name, msg))
                except asyncio.TimeoutError:
                    continue

            if not msgs_by_agent:
                quiet_rounds += 1
                if final_answer and quiet_rounds >= 5:
                    break
                continue
            quiet_rounds = 0

            for name, msg in msgs_by_agent:
                agent = agent_map[name]
                prompt = self._build_negotiation_prompt(name, msg)
                try:
                    result = await agent.think_and_act(prompt)
                except Exception as e:
                    await self.bus.send(
                        name, "editor", "response",
                        f"处理异常：{str(e)[:200]}", round_num=rounds,
                    )
                    continue
                response_text = result.get("response", "")
                if result.get("tool_calls"):
                    tool_calls_log.extend(result["tool_calls"])

                if not response_text.strip() or response_text.strip().upper() == "PASS":
                    continue

                targets = self._parse_targets(response_text)
                if not targets and name == "editor" and len(response_text) > 50:
                    final_answer = response_text
                    await self.bus.send(
                        "editor", "user", "response",
                        f"最终回答：{response_text[:300]}...", round_num=rounds,
                    )
                    continue
                if not targets and name == "librarian":
                    targets = ["editor"]

                for target in targets:
                    if target not in agent_map:
                        continue
                    await self.bus.send(
                        name, target, "response", response_text, round_num=rounds,
                    )

        return {
            "final_answer": final_answer or "对话未完成",
            "primary_agent": primary,
            "tool_calls": tool_calls_log,
        }

    async def negotiate(self, task: str, max_rounds: int = 5) -> dict:
        """真正的多 Agent 自由协商——每个 Agent 并发运行，自主决定对谁发言"""
        for name in ["collector", "curator", "librarian", "editor"]:
            self.bus.register(name)

        final_answer = None

        async def agent_loop(name: str, agent, max_sends: int = 3):
            nonlocal final_answer
            seen_hashes = set()
            send_count = 0

            for _ in range(max_rounds):
                try:
                    msg = await self.bus.receive(name, timeout=8)
                except asyncio.TimeoutError:
                    continue

                content_hash = hashlib.md5(
                    msg.get("content", "").encode()
                ).hexdigest()
                if content_hash in seen_hashes:
                    continue
                seen_hashes.add(content_hash)

                if send_count >= max_sends:
                    continue
                if final_answer and name != "editor":
                    continue

                prompt = self._build_negotiation_prompt(name, msg)
                result = await agent.think_and_act(prompt)
                response_text = result.get("response", "")

                if response_text.strip().upper() == "PASS":
                    continue

                targets = self._parse_targets(response_text)
                if not targets:
                    continue

                for target in targets:
                    send_count += 1
                    await self.bus.send(
                        from_agent=name,
                        to_agent=target,
                        msg_type="response",
                        content=response_text,
                        round_num=msg.get("round_num", 0) + 1,
                    )

                if name == "editor" and ("答案" in response_text or "回答" in response_text):
                    final_answer = response_text

        await self.bus.broadcast(
            "orchestrator", "proposal",
            f"任务：{task}\n@librarian 请检索相关内容\n@editor 请准备回答\n@curator 请记录主题",
            round_num=0,
        )

        await asyncio.gather(
            agent_loop("librarian", self.librarian),
            agent_loop("editor", self.editor),
            agent_loop("curator", self.curator),
            agent_loop("collector", self.collector),
        )

        return {
            "task": task,
            "final_answer": final_answer or "未收到最终回答",
            "message_history": self.bus.get_history(),
        }

    def _parse_targets(self, response_text: str) -> list[str]:
        targets = re.findall(r'@(\w+)', response_text)
        valid = {"collector", "curator", "librarian", "editor", "all"}
        seen = set()
        result = []
        for t in targets:
            if t in valid and t not in seen:
                seen.add(t)
                result.append(t)
        return result

    def _build_negotiation_prompt(self, agent_name: str, msg: dict) -> str:
        role_hints = {
            "collector": "你的职责：收到URL或文章内容后，用 fetch_url 或 load_document 入库。如果 @curator 建议调整数据源，回复你的方案。",
            "curator": "你的职责：收到文章后，用 check_similar 查重，用 record_topic 记录主题。如果重复或低质，告诉 @librarian 或 @collector。",
            "librarian": "你的职责：用 search 检索。检索后告诉 @editor 结果质量和矛盾。存储压力大时告诉 @curator。",
            "editor": "你的职责：综合检索结果回答用户。信息不足或矛盾时告诉 @librarian 补充。最终回答标注来源。",
        }
        hint = role_hints.get(agent_name, "")
        return f"""[协商消息]
发送者: {msg['from_agent']} | 类型: {msg['msg_type']}
内容: {msg['content']}

你是 {agent_name}。{hint}
收到上述消息后：用你的工具执行任务，如果需要协作用 @agent名 指定目标。与你无关则回复 PASS。"""
