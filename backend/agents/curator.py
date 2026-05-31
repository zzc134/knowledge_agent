"""分析员：判断内容质量、去重、分类"""

from .base import BaseAgent
from memory.long_term import record_access
from ingestion.embedder import embed_text
from retrieval.hybrid_search import dense_search


class CuratorAgent(BaseAgent):
    """分析员：筛选、分类、去重判断"""

    def __init__(self, message_bus=None):
        super().__init__(
            name="curator",
            tools={
                "check_similar": {
                    "description": "在知识库中搜索相似内容，判断是否有重复",
                    "params": {"content": "要检查的内容片段"},
                    "function": self._check_similar,
                },
                "record_topic": {
                    "description": "记录用户访问了某个主题",
                    "params": {"topic": "主题名"},
                    "function": self._record_topic,
                },
            },
        )
        self.message_bus = message_bus

    async def _check_similar(self, content: str) -> str:
        """查重：用 dense 检索检查是否有相似内容"""
        embedding = embed_text(content[:500])
        results = await dense_search(embedding, top_k=3)
        if not results:
            return "知识库中无相似内容"
        top = results[0]
        return (
            f"最相似内容(score={top['score']:.3f}): {top['content'][:200]}..."
        )

    async def _record_topic(self, topic: str) -> str:
        await record_access(topic)
        return f"已记录主题: {topic}"

    @property
    def system_prompt(self) -> str:
        return """你是内容策展人。你的职责是评估和筛选内容质量。

当收到一篇新文章时：
1. 判断内容质量（是否值得保存？）
2. 用 check_similar 检查知识库是否已有类似内容
3. 如果相似度高，建议关联而非重复存储
4. 提取文章的核心主题，用 record_topic 记录

【协商协议——必须严格遵守】
- 收到 @collector 的入库通知后，立即执行：先调 check_similar 查重，再调 record_topic 记录主题
- 无论查重结果如何，完成上述两步后必须 @librarian 告知："新内容已入库，主题为xxx，查重结果：xxx，请重新索引并检索"
- 如果发现文章与已有内容高度重复，额外 @collector 说明情况
- 不要跳过任何步骤，不要只回复而不执行工具"""
