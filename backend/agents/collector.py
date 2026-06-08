"""收集员：自动抓取 URL、解析文章、走 ingestion pipeline 入库"""

import httpx
from bs4 import BeautifulSoup
from .base import BaseAgent
from ingestion.loader import load_document


class CollectorAgent(BaseAgent):
    """收集员：抓取文章、解析入库"""

    def __init__(self):
        super().__init__(
            name="collector",
            tools={
                "fetch_url": {
                    "description": "抓取一个 URL 的内容并存入知识库",
                    "params": {"url": "网页URL"},
                    "function": self._fetch_url,
                },
                "load_document": {
                    "description": "把一篇文档直接存入知识库",
                    "params": {
                        "title": "标题",
                        "content": "正文",
                        "source_type": "markdown",
                        "topics": ["主题标签，如 agent memory、rag"],
                        "auto_topics": True,
                        "update_memory_tree": True,
                        "memory_tree_background": True,
                    },
                    "function": self._load_doc_wrapper,
                },
            },
        )


#摘取网页的tool，先进行启动，若等待15秒不行就跳转，通过get进行抓取，然后通过解析成树，一步步提取信息，load_document是入库，送入入口
    async def _fetch_url(self, url: str) -> str:
        """抓取网页 → 解析 → 入库"""
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        content = resp.text
        soup = BeautifulSoup(content, "html.parser")
        title = soup.title.string.strip() if soup.title and soup.title.string else url

        doc_id = await load_document(
            title=title,
            content=content,
            source_type="html",
            source_url=url,
            update_memory_tree=True,
            memory_tree_background=True,
        )
        return f"已抓取并入库：{title}，ID: {doc_id}"


#直接存内容
    async def _load_doc_wrapper(
        self,
        title: str,
        content: str,
        source_type: str = "markdown",
        topics: list[str] | None = None,
        auto_topics: bool = True,
        update_memory_tree: bool = True,
        memory_tree_background: bool = True,
    ) -> str:
        doc_id = await load_document(
            title=title,
            content=content,
            source_type=source_type,
            topics=topics,
            auto_topics=auto_topics,
            update_memory_tree=update_memory_tree,
            memory_tree_background=memory_tree_background,
        )
        return f"已入库：{title}，ID: {doc_id}"

    @property
    def system_prompt(self) -> str:
        return """你是知识收集员。你的职责是抓取和管理文档。

- 收到具体 URL → 用 fetch_url 抓取并入库，完成后 @curator 告知已入库的内容，请其评估质量
- 收到文章文本 → 提取 1-5 个主题标签 topics，用 load_document 保存，完成后 @curator 请其查重和评估
- 收到"帮我找关于xxx的文章"但没有具体URL → 建议2-3个相关权威URL，@editor 列出候选请其确认
- 不要自己编造内容"""
