"""入库主题标签处理。

这个模块不依赖数据库和 embedding，方便 ingestion、评估脚本、后续 Topic Tree 复用。
"""


def normalize_topics(topics: list[str] | None) -> list[str]:
    """规范化入库 topic。

    topics 是写入 Chunk.metadata_ 的主题标签，供 Topic Tree 直接建索引用。
    这里做三件事：去空白、转小写、去重。
    """
    if not topics:
        return []

    normalized = []
    seen = set()
    for topic in topics:
        topic_text = str(topic).strip().lower()
        if topic_text and topic_text not in seen:
            seen.add(topic_text)
            normalized.append(topic_text)
    return normalized
