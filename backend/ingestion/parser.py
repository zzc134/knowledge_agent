"""把 HTML/Markdown/纯文本转成干净的纯文字，给 RAG 知识库使用"""

from bs4 import BeautifulSoup
from markdown_it import MarkdownIt


def parse_html(content: str) -> str:
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


def parse_markdown(content: str) -> str:
    md = MarkdownIt()
    html = md.render(content)
    return parse_html(html)


def parse_text(content: str) -> str:
    return content.strip()


PARSERS = {
    "html": parse_html,
    "markdown": parse_markdown,
    "text": parse_text,
}


def parse_document(content: str, source_type: str) -> str:
    """入口：根据文档类型选择解析器，返回纯文本"""
    parser = PARSERS.get(source_type, parse_text)
    return parser(content)
