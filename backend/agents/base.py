"""所有 Agent 的父类——定义通用行为：调 LLM、执行工具、收消息"""

import json
import asyncio
from core.llm import llm_chat_with_retry
from config import get_settings

settings = get_settings()


class BaseAgent:
    """
    Agent 基类。
    每个 Agent 有独立的 system_prompt、工具集、模型路由、对话历史。
    """

    def __init__(self, name: str, tools: dict | None = None):
        self.name = name
        self.tools = tools or {}
        model_cfg = settings.model_routing.get(
            name, {"provider": "deepseek", "model": "deepseek-chat"}
        )
        self.provider = model_cfg["provider"]
        self.model = model_cfg["model"]
        self.conversation_history: list[dict] = []

    @property
    def system_prompt(self) -> str:
        raise NotImplementedError

    def tools_description(self) -> str:
        if not self.tools:
            return ""
        lines = []
        for tool_name, tool_info in self.tools.items():
            params = tool_info.get("params", {})
            lines.append(f"- {tool_name}: {tool_info['description']}")
            if params:
                lines.append(f"  参数: {json.dumps(params, ensure_ascii=False)}")
        return "\n".join(lines)

    def _build_full_system_prompt(self) -> str:
        parts = [self.system_prompt]
        if self.tools:
            parts.append(f"\n\n## 可用工具\n{self.tools_description()}")
            parts.append(
                '\n调用工具时，回复一个 JSON：\n{"tool": "工具名", "params": {"参数": "值"}}'
            )
            parts.append("不需要调工具时，直接回复用户。")
        return "\n".join(parts)

    async def _build_initial_messages(self, user_message: str) -> list[dict]:
        """构建第一次 LLM 调用的上下文。

        如果 Agent 绑定了 ShortTermMemory session，就使用 context assembler 注入：
        长期兴趣、Memory Tree 摘要、当前会话上下文和工具定义。
        没有 session 的 Agent 保持旧逻辑，避免影响 Collector/Curator/Librarian。
        """
        session = getattr(self, "session", None)
        if session is None:
            return [{"role": "system", "content": self._build_full_system_prompt()}]

        try:
            from context.assembler import assemble_context

            return await assemble_context(
                agent_system_prompt=self.system_prompt,
                session=session,
                tools_description=self.tools_description(),
                user_query=user_message,
            )
        except Exception:
            return [{"role": "system", "content": self._build_full_system_prompt()}]

    async def think_and_act(self, user_message: str) -> dict:
        """核心循环：多轮对话 + 工具调用，完整保留对话历史"""

        if not self.conversation_history:
            self.conversation_history.extend(
                await self._build_initial_messages(user_message)
            )
        else:
            self.conversation_history.append({"role": "user", "content": user_message})

        tool_calls_made = []
        max_turns = 3

        for _ in range(max_turns):
            response = await llm_chat_with_retry(
                messages=self.conversation_history,
                provider=self.provider,
                model=self.model,
            )

            tool_call = self._parse_tool_call(response)
            if tool_call and tool_call["name"] in self.tools:
                tool_result = await self._execute_tool(
                    tool_call["name"], tool_call["params"]
                )
                tool_calls_made.append({
                    "tool": tool_call["name"],
                    "params": tool_call["params"],
                    "result": tool_result,
                })
                self.conversation_history.append(
                    {"role": "assistant", "content": response}
                )
                self.conversation_history.append({
                    "role": "user",
                    "content": f"工具 {tool_call['name']} 返回:\n{tool_result}",
                })
            else:
                if tool_calls_made:
                    self.conversation_history.append(
                        {"role": "assistant", "content": response}
                    )
                    summary = await llm_chat_with_retry(
                        messages=self.conversation_history
                        + [
                            {
                                "role": "user",
                                "content": "请基于上述工具返回的结果，用自然语言给用户一个完整的回答。不要返回JSON，直接说话。",
                            }
                        ],
                        provider=self.provider,
                        model=self.model,
                    )
                    self.conversation_history.append(
                        {"role": "assistant", "content": summary}
                    )
                    return {"response": summary, "tool_calls": tool_calls_made}

                self.conversation_history.append(
                    {"role": "assistant", "content": response}
                )
                return {"response": response, "tool_calls": tool_calls_made}

        if tool_calls_made:
            summary = await llm_chat_with_retry(
                messages=self.conversation_history
                + [
                    {
                        "role": "user",
                        "content": "请用自然语言总结以上所有工具结果。",
                    }
                ],
                provider=self.provider,
                model=self.model,
            )
            self.conversation_history.append({"role": "assistant", "content": summary})
            return {"response": summary, "tool_calls": tool_calls_made}
        return {"response": response, "tool_calls": tool_calls_made}

    def _parse_tool_call(self, response: str) -> dict | None:
        text = response.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        elif "{" in text:
            start = text.find("{")
            depth = 0
            for i in range(start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        text = text[start : i + 1]
                        break

        try:
            parsed = json.loads(text)
            if "tool" in parsed:
                name = parsed["tool"]
                if name not in self.tools:
                    return None
                params = parsed.get("params", {})
                if not params:
                    params = {k: v for k, v in parsed.items() if k != "tool"}
                return {"name": name, "params": params}
        except json.JSONDecodeError:
            pass
        return None

    async def _execute_tool(self, tool_name: str, params: dict) -> str:
        func = self.tools[tool_name]["function"]
        try:
            result = (
                await func(**params)
                if asyncio.iscoroutinefunction(func)
                else func(**params)
            )
            return str(result)[:2000]
        except Exception as e:
            return f"工具执行错误: {e}"
