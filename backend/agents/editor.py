"""编辑：综合回答和生成简报"""

from .base import BaseAgent
from memory.short_term import ShortTermMemory


class EditorAgent(BaseAgent):
    """编辑：综合回答、生成简报"""

    def __init__(self, session: ShortTermMemory | None = None, llm_call_func=None):
        self.session = session
        self._llm_call = llm_call_func
        self._answer_func = self._build_answer_func()

        super().__init__(
            name="editor",
            tools={
                "answer_with_search": {
                    "description": "在知识库中搜索并综合回答用户问题",
                    "params": {"question": "用户的问题"},
                    "function": self._answer_func,
                },
            },
        )

    def _build_answer_func(self):
        """构建 search + synthesize 的回答工具"""
        import core.llm as llm_mod

        async def answer_with_search(question: str) -> str:
            from retrieval.retriever import retrieve

            llm_call_func = llm_mod.llm_call

            # 先走 Memory Tree：读取高层摘要路径，再下钻到 L0 chunks。
            # 如果树还没构建、没有命中，或者检索器异常，再回退到原来的混合检索。
            try:
                from memory.tree_retriever import retrieve_from_memory_tree

                tree_results = await retrieve_from_memory_tree(
                    question,
                    top_k=2,
                    max_chunks=4,
                )
            except Exception:
                tree_results = []

            if tree_results:
                memory_text_parts = []
                source_index = 1
                for result_index, result in enumerate(tree_results, start=1):
                    path_text = "\n".join(
                        f"- L{node.level} {node.title}: {node.summary[:500]}"
                        for node in result.memory_path
                    )
                    chunk_lines = []
                    for chunk in result.chunks:
                        chunk_lines.append(
                            f"[来源{source_index}] {chunk.content[:400]}"
                        )
                        source_index += 1

                    memory_text_parts.append(
                        f"## Memory Tree 命中 {result_index}\n"
                        f"命中节点：{result.matched_node.title}\n\n"
                        f"摘要路径：\n{path_text}\n\n"
                        f"原始证据：\n" + "\n\n".join(chunk_lines)
                    )

                memory_text = "\n\n".join(memory_text_parts)
                answer_prompt = f"""基于以下 Memory Tree 检索结果回答用户问题。

请先利用“摘要路径”理解整体背景，再依据“原始证据”回答。
必须标注信息来源编号，例如 [来源1]、[来源2]。
如果信息不足，请明确说明缺口，不要编造。

Memory Tree 检索结果：
{memory_text}

用户问题：{question}

请回答："""

                response = await llm_call_func(
                    system_prompt="你是一个知识助手，优先基于 Memory Tree 的摘要路径和原始证据回答用户问题。必须标注来源编号。",
                    user_message=answer_prompt,
                    provider=self.provider,
                    model=self.model,
                )
                return response

            results = await retrieve(question, llm_call_func, top_k=3)

            if not results:
                return "抱歉，知识库中没有找到相关信息"

            docs_text = "\n\n".join(
                f"[来源{i+1}] {r['content'][:400]}" for i, r in enumerate(results)
            )
            answer_prompt = f"""基于以下检索结果回答用户问题。标注信息来源。如果信息之间有矛盾，明确指出。

检索结果：
{docs_text}

用户问题：{question}

请回答："""

            response = await llm_call_func(
                system_prompt="你是一个知识助手，基于给定的检索结果回答用户问题。必须标注信息来源编号。",
                user_message=answer_prompt,
                provider=self.provider,
                model=self.model,
            )
            return response

        return answer_with_search

    @property
    def system_prompt(self) -> str:
        return """你是知识编辑。你的职责是基于知识库的内容回答用户问题。

【核心决策：先判断再行动】
收到 Librarian 的检索结果后，你必须先判断信息是否足够：

1. 信息足够 → 直接综合回答，标注来源（[来源1]、[来源2]），不要再 @ 任何人
2. 信息不足或完全不相关 → 第一步 @librarian 换关键词重搜一次；重搜后仍然无结果时：①诚实告诉用户"知识库暂无相关内容" ②用自己的知识给出回答并标注「以下基于模型自身知识」③@collector 请尝试从网上找相关文档的URL并抓取入库
3. 部分足够但缺关键细节 → 先用已有信息回答你能回答的部分，然后 @librarian 请补充检索
4. 信息来源之间有矛盾 → 在回答中标注 [⚠️冲突]

【回答要求】
- 自然流畅，不要返回 JSON
- 每个观点标注来源编号
- 如果 @curator 标记了低质内容，降低其权重或不引用"""
